"""
Module 7 — Fixed Asset Management tests.

Scenario A (register + SL depreciation math proof):
  Asset: Laptop, cost 12,000,000, salvage 2,000,000,
  36 months STRAIGHT_LINE, acquired 2026-06-01.
    register -> GL Dr Asset 12,000,000 / Cr Bank 12,000,000
  Monthly depreciation = (12M - 2M) / 36 = 277,777.78
  Run 3 months (Jul, Aug, Sep 2026):
    -> 3 schedule rows, monthly 277,777.78 each
    -> accumulated 833,333.33 (833,333.34 rounded split ok)
    -> book value = 12M - 833,333.33 = 11,166,666.67
    -> ONE aggregated JE per run: Dr Depr Expense = Cr Accum
  Double-run same period -> PERIOD_ALREADY_PROCESSED.

Scenario B (declining balance + salvage floor):
  Asset: Server, cost 10,000,000, salvage 1,000,000,
  60 months DECLINING_BALANCE, rate 40%/year.
  Month 1: 10,000,000 * (40/12/100) = 333,333.33
  Month 2: (10M - 333,333.33) * (0.4/12) = 322,222.22
  -> schedule amounts strictly decreasing; LEAST cap keeps
     book_value >= salvage.

Scenario C (disposal gain/loss math proof):
  Asset (after 3 months SL): book 11,166,666.67,
  accumulated 833,333.33. Dispose SALE proceeds 5,000,000:
    gain_loss = 5,000,000 - 11,166,666.67 = -6,166,666.67
    JE: Dr Accum Depr 833,333.33 + Dr Bank 5,000,000
        + Dr Loss 6,166,666.67 = Cr Asset 12,000,000
    -> status DISPOSED; double dispose rejected.

Scenario D (NULL role hardening - security regression):
  Raw asyncpg connection with NO session role
  (jwt.claims.role unset -> fn_current_role() IS NULL):
    register -> FORBIDDEN_ROLE (must NOT pass).
  This locks the NULL-bypass bug found in Modul 6.
"""

from __future__ import annotations

from decimal import Decimal

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from tests.test_procurement import _amt
from tests.test_sales import _bootstrap, _seed_accounts

DB = "postgresql://postgres:postgres@localhost:5432/apexledger_test"


async def _mk_accounts() -> dict:
    """Asset / accum-depr / depr-expense / bank accounts."""
    conn = await asyncpg.connect(DB)
    try:
        entity_id = await conn.fetchval(
            "SELECT entity_id FROM user_profiles LIMIT 1"
        )
        codes = [
            ("1500", "Peralatan Kantor", "ASSET"),
            ("1510", "Akumulasi Penyusutan", "ASSET"),
            ("6200", "Beban Penyusutan", "EXPENSE"),
            ("1020", "Bank BCA", "ASSET"),
            ("5200", "Rugi Penjualan Aset", "EXPENSE"),
        ]
        out = {}
        for code, name, atype in codes:
            aid = await conn.fetchval(
                "INSERT INTO chart_of_accounts "
                "(entity_id, account_code, account_name, "
                " account_type, normal_balance, level, "
                " is_postable, is_active) "
                "VALUES ($1, $2, $3, $4, 'DEBIT', 1, "
                "TRUE, TRUE) RETURNING id",
                entity_id, code, name, atype,
            )
            out[code] = str(aid)
        await conn.execute(
            "UPDATE entity_gl_defaults SET "
            "gl_depr_expense_default_account_id = $1 "
            "WHERE entity_id = $2",
            out["6200"], entity_id,
        )
        return out
    finally:
        await conn.close()


async def _register_asset(client, headers, accts, name,
                          cost, salvage, life, method="STRAIGHT_LINE",
                          rate=None) -> dict:
    body = {
        "asset_name": name,
        "asset_category": "TANGIBLE",
        "acquisition_date": "2026-06-01",
        "acquisition_cost": cost,
        "salvage_value": salvage,
        "useful_life_months": life,
        "depreciation_method": method,
        "gl_asset_account_id": accts["1500"],
        "gl_accum_depr_account_id": accts["1510"],
        "funding_account_id": accts["1020"],
    }
    if rate is not None:
        body["declining_rate_pct"] = rate
    r = await client.post(
        "/api/v1/assets", headers=headers, json=body
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _run_batch(client, headers, year, month) -> dict:
    r = await client.post(
        "/api/v1/assets/depreciation/batch",
        headers=headers,
        json={"period_year": year, "period_month": month},
    )
    return r


@pytest.mark.asyncio
async def test_register_sl_depreciation_math_proof():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        await _seed_accounts()
        accts = await _mk_accounts()

        asset = await _register_asset(
            client, headers, accts, "Laptop Engineering",
            "12000000", "2000000", 36,
        )
        assert asset["asset_code"].startswith("FA-2026-")
        assert asset["journal_entry_id"]

        # Acquisition JE balanced: 12,000,000 = 12,000,000.
        conn = await asyncpg.connect(DB)
        try:
            row = await conn.fetchrow(
                "SELECT SUM(jl.debit_amount) dr, "
                "SUM(jl.credit_amount) cr "
                "FROM journal_entries je "
                "JOIN journal_lines jl "
                " ON jl.journal_entry_id = je.id "
                "WHERE je.description LIKE "
                " 'Fixed Asset Acquisition%'"
            )
            assert _amt(row["dr"]) == _amt("12000000")
            assert _amt(row["cr"]) == _amt("12000000")
        finally:
            await conn.close()

        # 3 monthly runs.
        for year, month in [
            (2026, 7), (2026, 8), (2026, 9),
        ]:
            r = await _run_batch(client, headers, year, month)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["asset_count"] == 1
            assert _amt(body["total_depreciation"]) == _amt(
                "277777.78"
            )

        # Schedule rows + book value invariant.
        conn = await asyncpg.connect(DB)
        try:
            rows = await conn.fetch(
                "SELECT depreciation_amount, "
                "accumulated_after, book_value_after "
                "FROM asset_depreciation_schedule "
                "ORDER BY period_year, period_month"
            )
            assert len(rows) == 3
            for row in rows:
                assert _amt(row["depreciation_amount"]) == _amt(
                    "277777.78"
                )
            total = sum(
                Decimal(r["depreciation_amount"]) for r in rows
            )
            assert total == Decimal("833333.34")

            fa = await conn.fetchrow(
                "SELECT accumulated_depreciation, book_value, "
                "status FROM fixed_assets "
                "WHERE asset_name = 'Laptop Engineering'"
            )
            assert _amt(fa["accumulated_depreciation"]) == _amt(
                "833333.34"
            )
            assert _amt(fa["book_value"]) == _amt("11166666.66")
            assert str(fa["status"]) == "ACTIVE"
        finally:
            await conn.close()

        # Double-run rejected.
        r = await _run_batch(client, headers, 2026, 7)
        assert r.status_code in (409, 422), r.text
        assert "PERIOD_ALREADY_PROCESSED" in r.text


@pytest.mark.asyncio
async def test_declining_balance_decreasing_proof():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        await _seed_accounts()
        accts = await _mk_accounts()

        await _register_asset(
            client, headers, accts, "Server Rack",
            "10000000", "1000000", 60,
            method="DECLINING_BALANCE", rate="40",
        )

        for year, month in [(2026, 7), (2026, 8)]:
            r = await _run_batch(client, headers, year, month)
            assert r.status_code == 200, r.text

        conn = await asyncpg.connect(DB)
        try:
            rows = await conn.fetch(
                "SELECT depreciation_amount, book_value_after "
                "FROM asset_depreciation_schedule "
                "ORDER BY period_year, period_month"
            )
            assert len(rows) == 2
            m1 = Decimal(rows[0]["depreciation_amount"])
            m2 = Decimal(rows[1]["depreciation_amount"])
            # M1 = 10,000,000 * (40 / 12 / 100)
            #    = 333,333.33
            assert m1 == Decimal("333333.33")
            # M2 = (10M - 333,333.33) * (0.4/12)
            #    = 9,666,666.67 * 0.033333... = 322,222.22
            assert m2 == Decimal("322222.22")
            assert m1 > m2  # strictly decreasing
            # Salvage floor respected.
            assert Decimal(rows[1]["book_value_after"]) >= (
                Decimal("1000000")
            )
        finally:
            await conn.close()


@pytest.mark.asyncio
async def test_disposal_gain_loss_math_proof():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        await _seed_accounts()
        accts = await _mk_accounts()

        asset = await _register_asset(
            client, headers, accts, "Laptop Sales Team",
            "12000000", "2000000", 36,
        )
        for year, month in [(2026, 7), (2026, 8), (2026, 9)]:
            r = await _run_batch(client, headers, year, month)
            assert r.status_code == 200, r.text

        # Dispose: proceeds 5,000,000 < book 11,166,666.67.
        r = await client.post(
            f"/api/v1/assets/{asset['asset_id']}/dispose",
            headers=headers,
            json={
                "disposal_date": "2026-10-01",
                "disposal_type": "SALE",
                "disposal_proceeds": "5000000",
                "proceeds_account_id": accts["1020"],
                "gain_loss_account_id": accts["5200"],
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # gain_loss = 5,000,000 - 11,166,666.66
        assert _amt(body["gain_loss"]) == _amt("-6166666.66")

        conn = await asyncpg.connect(DB)
        try:
            # Disposal JE balanced:
            # Dr Accum 833,333.34 + Dr Bank 5,000,000
            #   + Dr Loss 6,166,666.66 = Cr Asset 12,000,000
            row = await conn.fetchrow(
                "SELECT SUM(jl.debit_amount) dr, "
                "SUM(jl.credit_amount) cr "
                "FROM journal_entries je "
                "JOIN journal_lines jl "
                " ON jl.journal_entry_id = je.id "
                "WHERE je.description LIKE 'Asset Disposal%'"
            )
            assert _amt(row["dr"]) == _amt("12000000")
            assert _amt(row["cr"]) == _amt("12000000")

            status = await conn.fetchval(
                "SELECT status FROM fixed_assets "
                "WHERE id = $1",
                asset["asset_id"],
            )
            assert str(status) == "DISPOSED"
        finally:
            await conn.close()

        # Double dispose rejected.
        r = await client.post(
            f"/api/v1/assets/{asset['asset_id']}/dispose",
            headers=headers,
            json={
                "disposal_date": "2026-10-02",
                "disposal_type": "WRITE_OFF",
                "disposal_proceeds": "0",
                "proceeds_account_id": accts["1020"],
                "gain_loss_account_id": accts["5200"],
            },
        )
        assert r.status_code in (409, 422), r.text
        assert "ASSET_ALREADY_DISPOSED" in r.text


@pytest.mark.asyncio
async def test_null_role_hardening():
    """No session role set -> RPC must reject, not pass.

    Locks the NULL-bypass found in Modul 6: when
    fn_current_role() IS NULL, `NOT IN` evaluates to NULL
    and the old check silently passed.
    """
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await _bootstrap(client)
        await _seed_accounts()
        accts = await _mk_accounts()

        conn = await asyncpg.connect(DB)
        try:
            entity_id = await conn.fetchval(
                "SELECT entity_id FROM user_profiles LIMIT 1"
            )
            # Ensure NO role is set on this raw session.
            await conn.execute(
                "SELECT set_config('jwt.claims.role', '', false)"
            )
            try:
                await conn.fetchval(
                    "SELECT fn_register_fixed_asset("
                    "$1::uuid, "
                    "'Hacker Asset'::varchar, "
                    "'TANGIBLE'::asset_category_enum, "
                    "CURRENT_DATE, 1000::numeric, "
                    "0::numeric, 12::smallint, "
                    "'STRAIGHT_LINE'"
                    "::depreciation_method_enum, "
                    "NULL::numeric, $2::uuid, $3::uuid, "
                    "$4::uuid)",
                    entity_id,
                    accts["1500"],
                    accts["1510"],
                    accts["1020"],
                )
                raised = False
            except asyncpg.exceptions.PostgresError as e:
                raised = "FORBIDDEN_ROLE" in str(e)
            assert raised, (
                "NULL role must be rejected (NULL-bypass "
                "regression)"
            )
        finally:
            await conn.close()
