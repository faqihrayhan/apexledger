"""
Module 6 — Treasury & Cash Management tests.

Scenario A (kasbon full lifecycle math proof):
  Threshold seed: KASBON >= 5,000,000 -> DIREKSI.
  Kasbon 6,000,000 "perjalanan dinas":
    -> create DRAFT
    -> submit -> PENDING_APPROVAL, required DIREKSI (6jt >= 5jt)
    -> approve (SUPER_ADMIN bootstrap) -> APPROVED
    -> disburse 6,000,000:
         GL: Dr Piutang Karyawan 6,000,000 / Cr Bank 6,000,000
    -> settle with expenses 5,500,000:
         GL: Dr Expense 5,500,000 + Dr Bank 500,000
             / Cr Piutang Karyawan 6,000,000
         refund = 500,000 (karyawan balikin sisa)
    -> status SETTLED; double settle rejected.

Scenario B (dynamic approval authority):
  Kasbon 6,000,000 requires DIREKSI. A FINANCE_OPERATOR
  cannot approve it (INSUFFICIENT_APPROVAL_AUTHORITY),
  even though FINANCE_OPERATOR can submit kasbon.

Scenario C (bank reconciliation auto-match):
  AR payment 88,800 exists; import bank statement lines:
    +88,800 (matches AR payment within +-3 days)
    -88,800 (matches AP payment if one exists in window)
    +999,999 (no match -> stays is_matched FALSE)
  auto-match -> matched_count >= 1; unmatched stays.

Scenario D (cash flow forecast):
  Entity with outstanding AR invoice (ISSUED, due in window)
  -> forecast returns INFLOW/AR_DUE row with correct amount.
"""

from __future__ import annotations

import uuid
from datetime import date

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from tests.test_procurement import (
    _amt,
    _mk_vendor,
    _seed_procurement_accounts,
)
from tests.test_sales import _bootstrap, _receive, _seed_accounts

DB = "postgresql://postgres:postgres@localhost:5432/apexledger_test"


async def _mk_bank_account(client, headers, ids) -> dict:
    """Create bank account + piutang karyawan account; ids."""
    conn = await asyncpg.connect(DB)
    try:
        entity_id = await conn.fetchval(
            "SELECT entity_id FROM user_profiles LIMIT 1"
        )
        bank_gl = await conn.fetchval(
            "INSERT INTO chart_of_accounts "
            "(entity_id, account_code, account_name, account_type, "
            " normal_balance, level, is_postable, is_active) "
            "VALUES ($1, '1020', 'Bank BCA', 'ASSET', 'DEBIT', "
            "1, TRUE, TRUE) RETURNING id",
            entity_id,
        )
        piutang_gl = await conn.fetchval(
            "INSERT INTO chart_of_accounts "
            "(entity_id, account_code, account_name, account_type, "
            " normal_balance, level, is_postable, is_active) "
            "VALUES ($1, '1250', 'Piutang Karyawan', 'ASSET', "
            "'DEBIT', 1, TRUE, TRUE) RETURNING id",
            entity_id,
        )
        expense_gl = await conn.fetchval(
            "INSERT INTO chart_of_accounts "
            "(entity_id, account_code, account_name, account_type, "
            " normal_balance, level, is_postable, is_active) "
            "VALUES ($1, '6100', 'Biaya Perjalanan Dinas', "
            "'EXPENSE', 'DEBIT', 1, TRUE, TRUE) RETURNING id",
            entity_id,
        )
    finally:
        await conn.close()

    r = await client.post(
        "/api/v1/treasury/bank-accounts",
        headers=headers,
        json={
            "bank_name": "Bank BCA",
            "account_number": "1234567890",
            "account_name": "PT Apex Koperasi",
            "gl_account_id": str(bank_gl),
        },
    )
    assert r.status_code == 201, r.text
    return {
        "bank": r.json(),
        "bank_gl": str(bank_gl),
        "piutang_gl": str(piutang_gl),
        "expense_gl": str(expense_gl),
    }


async def _mk_kasbon(client, headers, amount="6000000") -> dict:
    r = await client.post(
        "/api/v1/treasury/kasbon",
        headers=headers,
        json={
            "department_code": "SALES",
            "amount": amount,
            "purpose": "Perjalanan dinas Jakarta",
            "request_date": str(date.today()),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_kasbon_full_lifecycle_math_proof():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        ids = await _seed_accounts()

        # Seed KASBON threshold: >= 5jt -> DIREKSI.
        conn = await asyncpg.connect(DB)
        try:
            entity_id = await conn.fetchval(
                "SELECT entity_id FROM user_profiles LIMIT 1"
            )
            await conn.execute(
                "INSERT INTO approval_thresholds "
                "(entity_id, document_type, min_amount, "
                " required_role) "
                "VALUES ($1, 'KASBON', 5000000, 'DIREKSI')",
                entity_id,
            )
        finally:
            await conn.close()

        accs = await _mk_bank_account(client, headers, ids)
        kas = await _mk_kasbon(client, headers, "6000000")
        assert kas["status"] == "DRAFT"

        # Submit -> required DIREKSI (6jt >= 5jt threshold).
        r = await client.post(
            f"/api/v1/treasury/kasbon/{kas['id']}/submit",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["required_approval_role"] == "DIREKSI"

        # Approve by SUPER_ADMIN (bootstrap user).
        r = await client.post(
            f"/api/v1/treasury/kasbon/{kas['id']}/approve",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "APPROVED"

        # Disburse 6,000,000.
        r = await client.post(
            f"/api/v1/treasury/kasbon/{kas['id']}/disburse",
            headers=headers,
            json={
                "bank_account_id": accs["bank"]["id"],
                "piutang_karyawan_account_id": accs["piutang_gl"],
            },
        )
        assert r.status_code == 200, r.text

        conn = await asyncpg.connect(DB)
        try:
            row = await conn.fetchrow(
                "SELECT SUM(jl.debit_amount) dr, "
                "SUM(jl.credit_amount) cr "
                "FROM journal_entries je "
                "JOIN journal_lines jl "
                " ON jl.journal_entry_id = je.id "
                "WHERE je.description LIKE "
                " 'Kasbon Disbursement%'"
            )
            assert _amt(row["dr"]) == _amt("6000000")
            assert _amt(row["cr"]) == _amt("6000000")
        finally:
            await conn.close()

        # Settle: expenses 5,500,000 -> refund 500,000.
        r = await client.post(
            f"/api/v1/treasury/kasbon/{kas['id']}/settle",
            headers=headers,
            json={
                "settlement_date": str(date.today()),
                "piutang_karyawan_account_id": accs["piutang_gl"],
                "bank_account_id": accs["bank"]["id"],
                "lines": [
                    {
                        "expense_account_id": accs["expense_gl"],
                        "description": "Tiket + hotel",
                        "amount": "5500000",
                    }
                ],
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert _amt(body["actual_used"]) == _amt("5500000")
        assert _amt(body["refund"]) == _amt("500000")
        assert _amt(body["additional_claim"]) == _amt("0")

        conn = await asyncpg.connect(DB)
        try:
            row = await conn.fetchrow(
                "SELECT SUM(jl.debit_amount) dr, "
                "SUM(jl.credit_amount) cr "
                "FROM journal_entries je "
                "JOIN journal_lines jl "
                " ON jl.journal_entry_id = je.id "
                "WHERE je.description LIKE "
                " 'Kasbon Settlement%'"
            )
            # Dr Expense 5,500,000 + Dr Bank 500,000
            #   = Cr Piutang Karyawan 6,000,000
            assert _amt(row["dr"]) == _amt("6000000")
            assert _amt(row["cr"]) == _amt("6000000")

            status = await conn.fetchval(
                "SELECT status FROM kasbon_requests"
            )
            assert str(status) == "SETTLED"
        finally:
            await conn.close()

        # Double settle rejected.
        r = await client.post(
            f"/api/v1/treasury/kasbon/{kas['id']}/settle",
            headers=headers,
            json={
                "settlement_date": str(date.today()),
                "piutang_karyawan_account_id": accs["piutang_gl"],
                "bank_account_id": accs["bank"]["id"],
                "lines": [
                    {
                        "expense_account_id": accs["expense_gl"],
                        "description": "Duplicate",
                        "amount": "1000",
                    }
                ],
            },
        )
        assert r.status_code == 422, r.text
        assert "KASBON_ALREADY_SETTLED" in r.text or \
            "KASBON_NOT_DISBURSED" in r.text


@pytest.mark.asyncio
async def test_kasbon_approval_authority():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        await _seed_accounts()

        conn = await asyncpg.connect(DB)
        try:
            entity_id = await conn.fetchval(
                "SELECT entity_id FROM user_profiles LIMIT 1"
            )
            await conn.execute(
                "INSERT INTO approval_thresholds "
                "(entity_id, document_type, min_amount, "
                " required_role) "
                "VALUES ($1, 'KASBON', 5000000, 'DIREKSI')",
                entity_id,
            )

            # FINANCE_OPERATOR user (not SUPER_ADMIN).
            fin_id = await conn.fetchval(
                "INSERT INTO user_profiles "
                "(entity_id, full_name, email, hashed_password, "
                " role, is_active, force_password_reset) "
                "VALUES ($1, 'Fin Op', 'finop@test.id', 'x', "
                "'FINANCE_OPERATOR', TRUE, FALSE) RETURNING id",
                entity_id,
            )
            _ = fin_id
        finally:
            await conn.close()

        kas = await _mk_kasbon(client, headers, "6000000")
        r = await client.post(
            f"/api/v1/treasury/kasbon/{kas['id']}/submit",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["required_approval_role"] == "DIREKSI"

        # Approve by FINANCE_OPERATOR must fail: needs DIREKSI.
        # (Bootstrap user is SUPER_ADMIN which always passes;
        # here we verify the RPC rejects non-matching role by
        # creating a direct session as FINANCE_OPERATOR.)
        conn = await asyncpg.connect(DB)
        try:
            # Direct RPC call with FINANCE_OPERATOR context.
            # Session vars are jwt.claims.* (see inject_rls_context).
            await conn.execute(
                "SELECT set_config('jwt.claims.role', "
                "'FINANCE_OPERATOR', false)"
            )
            await conn.execute(
                "SELECT set_config('jwt.claims.entity_id', "
                "$1, false)",
                str(entity_id),
            )
            await conn.execute(
                "SELECT set_config('jwt.claims.user_id', "
                "$1, false)",
                str(fin_id),
            )
            try:
                await conn.fetchval(
                    "SELECT fn_approve_kasbon_request($1)",
                    kas["id"],
                )
                raised = False
            except asyncpg.exceptions.PostgresError as e:
                raised = (
                    "INSUFFICIENT_APPROVAL_AUTHORITY" in str(e)
                )
            assert raised, "FINANCE_OPERATOR approve must fail"
        finally:
            await conn.close()


@pytest.mark.asyncio
async def test_bank_reconciliation_auto_match():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        ids = await _seed_accounts()
        await _seed_procurement_accounts(ids)
        await _receive(client, headers, ids)
        vendor = await _mk_vendor(client, headers)

        # Build an AR payment 88,800 in the system.
        flow = await _full_ar_setup(client, headers, ids, vendor)

        accs = await _mk_bank_account(client, headers, ids)

        today = date.today()
        r = await client.post(
            f"/api/v1/treasury/bank-accounts/"
            f"{accs['bank']['id']}/statements",
            headers=headers,
            json={
                "lines": [
                    {
                        "statement_date": str(today),
                        "description": "TRANSFER IN",
                        "amount": "88800",
                    },
                    {
                        "statement_date": str(today),
                        "description": "BIAYA ADMIN",
                        "amount": "999999",
                    },
                ]
            },
        )
        assert r.status_code == 201, r.text

        r = await client.post(
            f"/api/v1/treasury/bank-accounts/"
            f"{accs['bank']['id']}/auto-match",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["matched_count"] == 1

        conn = await asyncpg.connect(DB)
        try:
            row = await conn.fetchrow(
                "SELECT is_matched, "
                "matched_transaction_type, "
                "matched_transaction_id "
                "FROM bank_statement_lines "
                "WHERE description = 'TRANSFER IN'"
            )
            assert row["is_matched"] is True
            assert row["matched_transaction_type"] == "AR_PAYMENT"
            assert str(row["matched_transaction_id"]) == str(
                flow["ar_payment_id"]
            )

            row = await conn.fetchrow(
                "SELECT is_matched "
                "FROM bank_statement_lines "
                "WHERE description = 'BIAYA ADMIN'"
            )
            assert row["is_matched"] is False
        finally:
            await conn.close()


async def _full_ar_setup(client, headers, ids, vendor):
    """SO -> confirm -> DO -> invoice -> AR payment 88,800."""
    from tests.test_sales import _deliver, _mk_customer, _mk_so

    cust_id = await _mk_customer(
        client, headers, "CUST-A", "1000000", 30
    )
    so = await _mk_so(
        client, headers, ids, cust_id, "SO-001", qty="10"
    )
    r = await client.post(
        f"/api/v1/sales/orders/{so['id']}/confirm", headers=headers
    )
    assert r.status_code == 200, r.text
    do_resp = await _deliver(client, headers, so, "10")
    do = do_resp.json()
    r = await client.post(
        f"/api/v1/sales/delivery-orders/"
        f"{do['delivery_order_id']}/invoice",
        headers=headers,
        json={"invoice_date": str(date.today())},
    )
    assert r.status_code in (200, 201), r.text
    invoice = r.json()
    inv_id = invoice["invoice_id"]

    conn = await asyncpg.connect(DB)
    try:
        inv_due = await conn.fetchval(
            "SELECT due_date FROM ar_invoices WHERE id = $1",
            uuid.UUID(str(inv_id)),
        )
    finally:
        await conn.close()

    r = await client.post(
        "/api/v1/sales/payments",
        headers=headers,
        json={
            "customer_id": cust_id,
            "payment_date": str(date.today()),
            "amount": "88800",
            "payment_method": "TRANSFER",
        },
    )
    assert r.status_code == 200, r.text
    ar_payment_id = r.json()["payment_id"]
    return {
        "invoice_id": inv_id,
        "ar_payment_id": ar_payment_id,
        "due_date": inv_due,
    }


@pytest.mark.asyncio
async def test_cash_flow_forecast():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        ids = await _seed_accounts()
        await _seed_procurement_accounts(ids)
        await _receive(client, headers, ids)
        vendor = await _mk_vendor(client, headers)

        await _full_ar_setup(client, headers, ids, vendor)

        # Invoice due = today + 30d term; default window is 4
        # weeks (28d) so request 6 weeks to include it.
        r = await client.get(
            "/api/v1/treasury/forecast?weeks_ahead=6",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) >= 1
        inflow_ar = [
            x for x in rows
            if x["category"] == "INFLOW"
            and x["source_type"] == "AR_DUE"
        ]
        assert len(inflow_ar) >= 1
        # Outstanding: 166,500 - 88,800 = 77,700.
        assert _amt(inflow_ar[0]["estimated_amount"]) == _amt(
            "77700"
        )
