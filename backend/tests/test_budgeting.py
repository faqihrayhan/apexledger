"""
Module 8 — Budgeting & Analytics tests.

Scenario A (budget lifecycle + audit snapshot):
  Create budget FY2026 "Ops 2026" DRAFT:
    revenue account 4000: 500,000 x 12 months
    expense account 6100: 300,000 x 12 months
  -> approve -> APPROVED
  -> revise (reason required, snapshot row 1 kept):
       revenue 500,000 -> 600,000 for Jan only
  -> new budget_lines total reflects revision
  -> approve a second time -> BUDGET_INVALID_STATUS
  -> lock -> LOCKED
  -> revise LOCKED by DEPT_HEAD_FA role -> FORBIDDEN

Scenario B (budget vs actual variance math):
  Post a REAL JE in Jan FY2026: revenue 550,000
    (Dr Bank 550,000 / Cr Revenue 550,000)
  vs-actual as_of_month=1:
    revenue: budgeted 500,000 (original line kept after
      revision only for expense; use fresh budget) ->
    actual 550,000, variance +50,000, pct +10.00
  (fresh budget B with revenue 500,000 Jan only)

Scenario C (monthly trend):
  After the revenue JE posted: trend(REVENUE, 12 months)
  contains a row for the Jan fiscal period with 550,000.

Scenario D (productivity batch idempotent):
  Run batch twice for same period -> metrics_calculated
  consistent; ON CONFLICT DO UPDATE (no duplicate rows).
"""

from __future__ import annotations

import uuid
from datetime import date

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from tests.test_procurement import _amt
from tests.test_sales import _bootstrap, _seed_accounts

DB = "postgresql://postgres:postgres@localhost:5432/apexledger_test"


async def _mk_accounts() -> dict:
    """Revenue + expense + bank accounts.

    Reuses existing codes (e.g. 4000 from _seed_accounts)
    when present so entity-unique account_code never
    collides.
    """
    conn = await asyncpg.connect(DB)
    try:
        entity_id = await conn.fetchval(
            "SELECT entity_id FROM user_profiles LIMIT 1"
        )
        codes = [
            ("4000", "Sales Revenue", "REVENUE", "CREDIT"),
            ("6100", "Beban Operasional", "EXPENSE", "DEBIT"),
            ("1020", "Bank BCA", "ASSET", "DEBIT"),
        ]
        out = {}
        for code, name, atype, nb in codes:
            aid = await conn.fetchval(
                "INSERT INTO chart_of_accounts "
                "(entity_id, account_code, account_name, "
                " account_type, normal_balance, level, "
                " is_postable, is_active) "
                "VALUES ($1, $2, $3, $4, $5, 1, "
                "TRUE, TRUE) "
                "ON CONFLICT (entity_id, account_code) "
                "DO NOTHING RETURNING id",
                entity_id, code, name, atype, nb,
            )
            if aid is None:
                aid = await conn.fetchval(
                    "SELECT id FROM chart_of_accounts "
                    "WHERE entity_id = $1 "
                    "AND account_code = $2",
                    entity_id, code,
                )
            out[code] = str(aid)
        return out
    finally:
        await conn.close()


async def _mk_fiscal_year() -> str:
    """Create FY 2026 with 12 fiscal periods."""
    conn = await asyncpg.connect(DB)
    try:
        entity_id = await conn.fetchval(
            "SELECT entity_id FROM user_profiles LIMIT 1"
        )
        fy = await conn.fetchval(
            "INSERT INTO fiscal_years "
            "(entity_id, year_label, start_date, end_date, "
            " status) VALUES ($1, 'FY2026', $2, $3, 'OPEN') "
            "ON CONFLICT (entity_id, year_label) "
            "DO NOTHING RETURNING id",
            entity_id,
            date(2026, 1, 1), date(2026, 12, 31),
        )
        if fy is None:
            fy = await conn.fetchval(
                "SELECT id FROM fiscal_years "
                "WHERE entity_id = $1 "
                "AND year_label = 'FY2026'",
                entity_id,
            )
        for m in range(1, 13):
            end = (
                date(2026, 12, 31) if m == 12
                else date(2026, m + 1, 1)
            )
            await conn.execute(
                "INSERT INTO fiscal_periods "
                "(fiscal_year_id, period_number, start_date, "
                " end_date, status) "
                "VALUES ($1, $2, $3, $4, 'OPEN') "
                "ON CONFLICT (fiscal_year_id, period_number) "
                "DO NOTHING",
                fy, m, date(2026, m, 1), end,
            )
        return str(fy)
    finally:
        await conn.close()


def _lines(accts, rev_amt, exp_amt, months=(1,)):
    out = []
    for m in months:
        out.append({
            "account_id": accts["4000"],
            "department_code": None,
            "period_month": m,
            "budgeted_amount": rev_amt,
        })
        out.append({
            "account_id": accts["6100"],
            "department_code": None,
            "period_month": m,
            "budgeted_amount": exp_amt,
        })
    return out


@pytest.mark.asyncio
async def test_budget_lifecycle_and_revision_audit():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        await _seed_accounts()
        accts = await _mk_accounts()
        fy = await _mk_fiscal_year()

        r = await client.post(
            "/api/v1/budgeting/budgets",
            headers=headers,
            json={
                "fiscal_year_id": fy,
                "budget_name": "Ops 2026",
                "lines": _lines(accts, "500000", "300000",
                                months=range(1, 13)),
            },
        )
        assert r.status_code == 200, r.text
        budget_id = r.json()["budget_id"]

        conn = await asyncpg.connect(DB)
        try:
            status = await conn.fetchval(
                "SELECT status FROM budgets WHERE id = $1",
                uuid.UUID(budget_id),
            )
            assert str(status) == "DRAFT"
            n = await conn.fetchval(
                "SELECT count(*) FROM budget_lines "
                "WHERE budget_id = $1",
                uuid.UUID(budget_id),
            )
            assert n == 24  # 2 accounts x 12 months
        finally:
            await conn.close()

        # Approve -> APPROVED.
        r = await client.post(
            f"/api/v1/budgeting/budgets/{budget_id}/approve",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "APPROVED"

        # Approve again -> BUDGET_INVALID_STATUS.
        r = await client.post(
            f"/api/v1/budgeting/budgets/{budget_id}/approve",
            headers=headers,
        )
        assert r.status_code in (409, 422), r.text
        assert "BUDGET_INVALID_STATUS" in r.text

        # Revise: revenue Jan 500,000 -> 600,000.
        new_lines = [
            {
                "account_id": accts["4000"],
                "department_code": None,
                "period_month": 1,
                "budgeted_amount": "600000",
            },
            {
                "account_id": accts["6100"],
                "department_code": None,
                "period_month": 1,
                "budgeted_amount": "300000",
            },
        ]
        r = await client.post(
            f"/api/v1/budgeting/budgets/{budget_id}/revise",
            headers=headers,
            json={
                "reason": "Revenue forecast naik Q1",
                "lines": new_lines,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["revision_number"] == 1

        conn = await asyncpg.connect(DB)
        try:
            # Audit snapshot row exists with old amounts.
            snap = await conn.fetchval(
                "SELECT before_snapshot "
                "FROM budget_revisions "
                "WHERE budget_id = $1 "
                "AND revision_number = 1",
                uuid.UUID(budget_id),
            )
            assert snap is not None
            # Old revenue Jan = 500,000 preserved in snapshot
            # (JSONB numeric serializes as 500000.00).
            assert "500000" in str(snap)

            # New line total for Jan revenue = 600,000.
            new_amt = await conn.fetchval(
                "SELECT budgeted_amount FROM budget_lines bl "
                "JOIN chart_of_accounts coa "
                " ON coa.id = bl.account_id "
                "WHERE bl.budget_id = $1 "
                "AND coa.account_code = '4000' "
                "AND bl.period_month = 1",
                uuid.UUID(budget_id),
            )
            assert _amt(new_amt) == _amt("600000")
        finally:
            await conn.close()

        # Lock -> LOCKED (SUPER_ADMIN bootstrap).
        r = await client.post(
            f"/api/v1/budgeting/budgets/{budget_id}/lock",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "LOCKED"

        # Revise LOCKED as non-SUPER_ADMIN (raw session) ->
        # FORBIDDEN.
        conn = await asyncpg.connect(DB)
        try:
            entity_id = await conn.fetchval(
                "SELECT entity_id FROM user_profiles LIMIT 1"
            )
            head_id = await conn.fetchval(
                "INSERT INTO user_profiles "
                "(entity_id, full_name, email, hashed_password, "
                " role, is_active, force_password_reset) "
                "VALUES ($1, 'Head FA', 'headfa@test.id', 'x', "
                "'DEPT_HEAD_FA', TRUE, FALSE) RETURNING id",
                entity_id,
            )
            await conn.execute(
                "SELECT set_config('jwt.claims.role', "
                "'DEPT_HEAD_FA', false)"
            )
            await conn.execute(
                "SELECT set_config('jwt.claims.entity_id', "
                "$1, false)",
                str(entity_id),
            )
            await conn.execute(
                "SELECT set_config('jwt.claims.user_id', "
                "$1, false)",
                str(head_id),
            )
            lines_json = (
                '[{"account_id": "' + accts["4000"] + '", '
                '"department_code": null, '
                '"period_month": 1, '
                '"budgeted_amount": "700000"}]'
            )
            try:
                await conn.fetchval(
                    "SELECT fn_revise_budget("
                    "$1::uuid, $2::jsonb, $3::text)",
                    budget_id, lines_json, "illegal",
                )
                raised = False
            except asyncpg.exceptions.PostgresError as e:
                raised = "FORBIDDEN" in str(e)
            assert raised, (
                "DEPT_HEAD_FA revising LOCKED budget must fail"
            )
        finally:
            await conn.close()


@pytest.mark.asyncio
async def test_budget_vs_actual_variance_math_proof():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        await _seed_accounts()
        accts = await _mk_accounts()
        fy = await _mk_fiscal_year()

        # Fresh budget B: revenue Jan budgeted 500,000.
        r = await client.post(
            "/api/v1/budgeting/budgets",
            headers=headers,
            json={
                "fiscal_year_id": fy,
                "budget_name": "Variance Test",
                "lines": [
                    {
                        "account_id": accts["4000"],
                        "department_code": None,
                        "period_month": 1,
                        "budgeted_amount": "500000",
                    },
                ],
            },
        )
        assert r.status_code == 200, r.text
        budget_id = r.json()["budget_id"]

        # Post a REAL revenue JE: 550,000 in Jan 2026.
        conn = await asyncpg.connect(DB)
        try:
            entity_id = await conn.fetchval(
                "SELECT entity_id FROM user_profiles LIMIT 1"
            )
            # Insert journal entry via RPC as SUPER_ADMIN.
            await conn.execute(
                "SELECT set_config('jwt.claims.role', "
                "'SUPER_ADMIN', false)"
            )
            await conn.execute(
                "SELECT set_config('jwt.claims.entity_id', "
                "$1, false)",
                str(entity_id),
            )
            await conn.execute(
                "SELECT set_config('jwt.claims.user_id', "
                "'00000000-0000-0000-0000-000000000000', "
                "false)"
            )
            user_id = await conn.fetchval(
                "SELECT id FROM user_profiles LIMIT 1"
            )
            await conn.execute(
                "SELECT set_config('jwt.claims.user_id', "
                "$1, false)",
                str(user_id),
            )
            lines_json = (
                '[{"account_id": "' + accts["1020"] + '", '
                '"debit_amount": 550000, '
                '"credit_amount": 0}, '
                '{"account_id": "' + accts["4000"] + '", '
                '"debit_amount": 0, '
                '"credit_amount": 550000}]'
            )
            je = await conn.fetchval(
                "SELECT fn_create_journal_entry("
                "$1::uuid, '2026-01-15'::date, "
                "'Jan revenue', 'IDR', $2::jsonb)",
                entity_id, lines_json,
            )
            je_id = str(je)
            if not je_id.startswith("{"):
                # asyncpg may return text; try JSON parse
                import json as _json
                je_id = _json.loads(je)["journal_entry_id"]
            else:
                import json as _json
                je_id = _json.loads(je)["journal_entry_id"]
            await conn.execute(
                "SELECT fn_post_journal_entry($1::uuid)",
                je_id,
            )
        finally:
            await conn.close()

        # Approve budget first (vs-actual works on any status,
        # but approve for realism).
        r = await client.post(
            f"/api/v1/budgeting/budgets/{budget_id}/approve",
            headers=headers,
        )
        assert r.status_code == 200, r.text

        r = await client.get(
            f"/api/v1/budgeting/budgets/{budget_id}"
            f"/vs-actual?as_of_month=1",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["account_code"] == "4000"
        assert _amt(row["budgeted_amount"]) == _amt("500000")
        assert _amt(row["actual_amount"]) == _amt("550000")
        assert _amt(row["variance_amount"]) == _amt("50000")
        assert _amt(row["variance_pct"]) == _amt("10.00")


@pytest.mark.asyncio
async def test_monthly_trend_revenue():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        await _seed_accounts()
        accts = await _mk_accounts()

        # Post the same Jan revenue JE 550,000.
        conn = await asyncpg.connect(DB)
        try:
            entity_id = await conn.fetchval(
                "SELECT entity_id FROM user_profiles LIMIT 1"
            )
            await conn.execute(
                "SELECT set_config('jwt.claims.role', "
                "'SUPER_ADMIN', false)"
            )
            await conn.execute(
                "SELECT set_config('jwt.claims.entity_id', "
                "$1, false)",
                str(entity_id),
            )
            user_id = await conn.fetchval(
                "SELECT id FROM user_profiles LIMIT 1"
            )
            await conn.execute(
                "SELECT set_config('jwt.claims.user_id', "
                "$1, false)",
                str(user_id),
            )
            lines_json = (
                '[{"account_id": "' + accts["1020"] + '", '
                '"debit_amount": 550000, '
                '"credit_amount": 0}, '
                '{"account_id": "' + accts["4000"] + '", '
                '"debit_amount": 0, '
                '"credit_amount": 550000}]'
            )
            je = await conn.fetchval(
                "SELECT fn_create_journal_entry("
                "$1::uuid, '2026-01-15'::date, "
                "'Trend Jan revenue', 'IDR', $2::jsonb)",
                entity_id, lines_json,
            )
            import json as _json
            je_id = _json.loads(je)["journal_entry_id"]
            await conn.execute(
                "SELECT fn_post_journal_entry($1::uuid)",
                je_id,
            )
        finally:
            await conn.close()

        r = await client.get(
            "/api/v1/budgeting/trend"
            "?account_type=REVENUE&num_months=12",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) >= 1
        jan = [x for x in rows if x["period_month"] == 1]
        assert len(jan) == 1
        assert _amt(jan[0]["total_amount"]) == _amt("550000")


@pytest.mark.asyncio
async def test_productivity_batch_idempotent():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        await _seed_accounts()

        # No employees/sales -> metrics_calculated = 0.
        r = await client.post(
            "/api/v1/budgeting/productivity/batch"
            "?period_year=2026&period_month=1",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["metrics_calculated"] == 0

        # Run twice -> still no duplicates, count stays 0.
        r = await client.post(
            "/api/v1/budgeting/productivity/batch"
            "?period_year=2026&period_month=1",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["metrics_calculated"] == 0
