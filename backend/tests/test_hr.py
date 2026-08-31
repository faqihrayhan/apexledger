"""
Module 2 — HR Payroll integration tests.

Math proof values are computed BY HAND from the official rules
(PMK 168/2023 TER table, BPJS 2025 rates, Kepmenakertrans 1/173):
the test asserts exact amounts, mirroring nothing.

Scenario:
- Entity + fiscal year 2026 via setup wizard (SUPER_ADMIN).
- Company calendar: Aug 2026 weekdays (21 working days).
- Employee A: MONTHLY, TK0, base 10,000,000, 10 OT hours, 2 UNPAID_LEAVE.
  * hourly = 10,000,000/173 = 57,803.4682...
  * OT pay  = 10 x hourly x 1.5       = 867,052.02
  * gross    = 10,867,052.02
  * TER A (10.7jt < g <= 11.05jt) 3%  -> PPh21 326,011.56
  * BPJS EE: KES 100,000 + JHT 200,000 + JP 100,000 = 400,000.00
  * denda    = 2/21 x 10,000,000       = 952,380.95
  * net      = 9,188,659.51
- Employee B: DAILY, K1, rate 500,000/day, 2 UNPAID_LEAVE (19 paid days).
  * gross    = 19 x 500,000            = 9,500,000.00
  * TER B (9.2jt < g <= 10.75jt) 1.5%  -> PPh21 142,500.00
  * BPJS EE: 1% + 2% + 1% of 500,000  = 20,000.00
  * net      = 9,337,500.00

Accrual journal (approve): Dr 20,367,052.02 = Cr 20,367,052.02.
Disbursement: Dr AP Gaji 18,526,159.51 = Cr Kas.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

TEST_DSN = "postgresql://postgres:postgres@localhost:5432/apexledger_test"

ADMIN_EMAIL = "owner@test.id"
ADMIN_PASSWORD = "S3curePass!x"


def _amt(value: str) -> Decimal:
    """Compare money as Decimal (JSONB strips trailing zeros)."""
    return Decimal(value)

# Hand-computed proof values (RPC rounds the hourly rate to 2 decimals
# before multiplying — money per hour — so OT pay follows that rounding).
# A: hourly 10,000,000/173 = 57,803.47; OT = 10 x 57,803.47 x 1.5 = 867,052.05
A_GROSS = "10867052.05"
A_DEDUCTION = "1678392.51"
A_NET = "9188659.54"
B_GROSS = "9500000.00"
B_DEDUCTION = "162500.00"
B_NET = "9337500.00"
TOTAL_NET = "18526159.54"
ACCRUAL_TOTAL = "20367052.05"
# Trial balance nets per account:
# Dr 5101 19,414,671.10 (salary exp minus denda contra) = Cr BPJS 420,000
#   + PPh21 468,511.56 + Kas 18,526,159.54 (AP Gaji nets to zero).
TB_TOTAL = "19414671.10"


async def _bootstrap(client: AsyncClient) -> str:
    """Run the setup wizard and return the admin access token."""
    resp = await client.post(
        "/api/v1/system/setup",
        json={
            "entity_code": "TEST",
            "entity_name": "Test Entity",
            "base_currency_code": "IDR",
            "fiscal_year": 2026,
            "admin_email": ADMIN_EMAIL,
            "admin_full_name": "Owner",
            "admin_password": ADMIN_PASSWORD,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def _seed_calendar_and_attendance(emp_a: str, emp_b: str) -> None:
    """Seed Aug-2026 weekday calendar + attendance via raw SQL.

    Superuser connection: bypasses RLS for test fixtures only.
    """
    conn = await asyncpg.connect(TEST_DSN)
    try:
        entity_id = await conn.fetchval("SELECT id FROM entities LIMIT 1")

        # Calendar: every weekday in Aug 2026 is a working day.
        rows = []
        for day in range(1, 32):
            d = date(2026, 8, day)
            if d.weekday() < 5:
                rows.append((entity_id, d))
        await conn.executemany(
            "INSERT INTO company_calendar (entity_id, calendar_date, "
            "is_working_day) VALUES ($1, $2, TRUE)",
            rows,
        )

        # Employee A: 1 PRESENT day with 10 OT hours + 2 UNPAID_LEAVE.
        await conn.executemany(
            "INSERT INTO attendance_records "
            "(employee_id, work_date, status, overtime_hours) "
            "VALUES ($1, $2, $3, $4)",
            [
                (emp_a, date(2026, 8, 3), "PRESENT", Decimal("10")),
                (emp_a, date(2026, 8, 4), "UNPAID_LEAVE", Decimal("0")),
                (emp_a, date(2026, 8, 5), "UNPAID_LEAVE", Decimal("0")),
            ],
        )

        # Employee B: 2 UNPAID_LEAVE days (no overtime).
        await conn.executemany(
            "INSERT INTO attendance_records "
            "(employee_id, work_date, status, overtime_hours) "
            "VALUES ($1, $2, $3, $4)",
            [
                (emp_b, date(2026, 8, 4), "UNPAID_LEAVE", Decimal("0")),
                (emp_b, date(2026, 8, 5), "UNPAID_LEAVE", Decimal("0")),
            ],
        )
    finally:
        await conn.close()


async def _map_component_gl_accounts() -> dict[str, str]:
    """Point payroll components at GL accounts (config table update)."""
    accounts = {
        "5101": "Salary Expense",
        "2101": "BPJS Payable",
        "2102": "PPh21 Payable",
        "2103": "AP Gaji",
        "1001": "Kas",
    }
    mapping = {
        "BASIC": "5101",
        "OVERTIME": "5101",
        "DENDA_UNPAID": "5101",
        "BPJS_KES_EE": "2101",
        "BPJS_JHT_EE": "2101",
        "BPJS_JP_EE": "2101",
        "PPH21": "2102",
    }
    created: dict[str, str] = {}
    conn = await asyncpg.connect(TEST_DSN)
    try:
        entity_id = await conn.fetchval("SELECT id FROM entities LIMIT 1")
        for code, name in accounts.items():
            acc_type = "ASSET" if code.startswith("1") else (
                "EXPENSE" if code.startswith("5") else "LIABILITY"
            )
            acc_id = await conn.fetchval(
                "INSERT INTO chart_of_accounts "
                "(entity_id, account_code, account_name, account_type, "
                " normal_balance, level, is_postable, is_active) "
                "VALUES ($1, $2, $3, $4, $5, 1, TRUE, TRUE) RETURNING id",
                entity_id,
                code,
                name,
                acc_type,
                "DEBIT" if acc_type in ("ASSET", "EXPENSE") else "CREDIT",
            )
            created[code] = str(acc_id)

        for comp, acc_code in mapping.items():
            await conn.execute(
                "UPDATE payroll_component_master SET gl_account_id = $1 "
                "WHERE code = $2",
                uuid.UUID(created[acc_code]),
                comp,
            )
    finally:
        await conn.close()
    return created


@pytest.mark.asyncio
async def test_payroll_full_lifecycle_math_proof():
    """Calculate -> approve -> disburse with hand-computed amounts."""
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}

        # -- Employees --------------------------------------------------
        resp = await client.post(
            "/api/v1/hr/employees",
            headers=headers,
            json={
                "employee_code": "EMP-001",
                "full_name": "Andi Monthly",
                "employment_type": "MONTHLY",
                "base_salary": "10000000",
                "ptkp_status": "TK0",
                "hire_date": "2024-01-15",
            },
        )
        assert resp.status_code == 201, resp.text
        emp_a = resp.json()["id"]

        resp = await client.post(
            "/api/v1/hr/employees",
            headers=headers,
            json={
                "employee_code": "EMP-002",
                "full_name": "Budi Daily",
                "employment_type": "DAILY",
                "base_salary": "500000",
                "ptkp_status": "K1",
                "hire_date": "2024-01-15",
            },
        )
        assert resp.status_code == 201, resp.text
        emp_b = resp.json()["id"]

        # -- Period ------------------------------------------------------
        resp = await client.post(
            "/api/v1/hr/payroll/periods",
            headers=headers,
            json={
                "period_year": 2026,
                "period_month": 8,
                "start_date": "2026-08-01",
                "end_date": "2026-08-31",
            },
        )
        assert resp.status_code == 201, resp.text
        period_id = resp.json()["id"]

        # -- Fixtures: calendar, attendance, component GL mapping --------
        await _seed_calendar_and_attendance(emp_a, emp_b)
        accounts = await _map_component_gl_accounts()

        # -- Calculate A --------------------------------------------------
        resp = await client.post(
            "/api/v1/hr/payroll/calculate",
            headers=headers,
            json={
                "employee_id": emp_a,
                "payroll_period_id": period_id,
            },
        )
        assert resp.status_code == 200, resp.text
        assert _amt(resp.json()["net_pay"]) == _amt(A_NET)

        # -- Calculate B --------------------------------------------------
        resp = await client.post(
            "/api/v1/hr/payroll/calculate",
            headers=headers,
            json={
                "employee_id": emp_b,
                "payroll_period_id": period_id,
            },
        )
        assert resp.status_code == 200, resp.text
        assert _amt(resp.json()["net_pay"]) == _amt(B_NET)

        # -- Exact per-employee breakdown ---------------------------------
        resp = await client.get(
            f"/api/v1/hr/payroll/periods/{period_id}/entries",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        entries = {e["employee_id"]: e for e in resp.json()}
        assert _amt(entries[emp_a]["gross_earning"]) == _amt(A_GROSS)
        assert _amt(entries[emp_a]["total_deduction"]) == _amt(A_DEDUCTION)
        assert _amt(entries[emp_a]["net_pay"]) == _amt(A_NET)
        assert entries[emp_a]["working_days"] == 21
        assert entries[emp_a]["unpaid_days"] == 2
        assert _amt(entries[emp_b]["gross_earning"]) == _amt(B_GROSS)
        assert _amt(entries[emp_b]["total_deduction"]) == _amt(B_DEDUCTION)
        assert _amt(entries[emp_b]["net_pay"]) == _amt(B_NET)

        # -- Approve (accrual posting) -------------------------------------
        resp = await client.post(
            "/api/v1/hr/payroll/approve",
            headers=headers,
            json={
                "payroll_period_id": period_id,
                "ap_gaji_account_id": accounts["2103"],
            },
        )
        assert resp.status_code == 200, resp.text
        accrual_je = resp.json()["journal_entry_id"]

        # Accrual journal must balance at exactly the hand-computed total.
        conn = await asyncpg.connect(TEST_DSN)
        try:
            dr, cr = await conn.fetchrow(
                "SELECT COALESCE(SUM(debit_amount),0), "
                "COALESCE(SUM(credit_amount),0) "
                "FROM journal_lines WHERE journal_entry_id = $1",
                accrual_je,
            )
            assert _amt(str(dr)) == _amt(ACCRUAL_TOTAL), f"Dr {dr} != {ACCRUAL_TOTAL}"
            assert _amt(str(cr)) == _amt(ACCRUAL_TOTAL), f"Cr {cr} != {ACCRUAL_TOTAL}"
            status = await conn.fetchval(
                "SELECT status FROM journal_entries WHERE id = $1",
                accrual_je,
            )
            assert status == "POSTED"
        finally:
            await conn.close()

        # -- Disburse (payment posting) ------------------------------------
        resp = await client.post(
            "/api/v1/hr/payroll/disburse",
            headers=headers,
            json={
                "payroll_period_id": period_id,
                "kas_bank_account_id": accounts["1001"],
            },
        )
        assert resp.status_code == 200, resp.text
        assert _amt(resp.json()["total_net"]) == _amt(TOTAL_NET)
        payment_je = resp.json()["journal_entry_id"]

        conn = await asyncpg.connect(TEST_DSN)
        try:
            dr, cr = await conn.fetchrow(
                "SELECT COALESCE(SUM(debit_amount),0), "
                "COALESCE(SUM(credit_amount),0) "
                "FROM journal_lines WHERE journal_entry_id = $1",
                payment_je,
            )
            assert _amt(str(dr)) == _amt(TOTAL_NET)
            assert _amt(str(cr)) == _amt(TOTAL_NET)

            period_status = await conn.fetchval(
                "SELECT status FROM payroll_periods WHERE id = $1",
                uuid.UUID(period_id),
            )
            assert period_status == "DISBURSED"
        finally:
            await conn.close()

        # -- Trial balance still proves the ledger -------------------------
        resp = await client.get(
            "/api/v1/gl/reports/trial-balance?as_of=2026-08-31",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        tb = resp.json()
        assert tb["is_balanced"] is True
        assert _amt(str(tb["grand_total_debit"])) == _amt(
            str(tb["grand_total_credit"])
        )
        assert _amt(str(tb["grand_total_debit"])) == _amt(TB_TOTAL)


@pytest.mark.asyncio
async def test_payroll_role_guards():
    """Non-finance roles blocked at the API; FINANCE_OPERATOR cannot approve."""
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await _bootstrap(client)  # wizard once-only; token unused here

        # Create a SALES_OPERATOR user (via direct insert; setup wizard
        # only creates the SUPER_ADMIN).
        conn = await asyncpg.connect(TEST_DSN)
        try:
            entity_id = await conn.fetchval("SELECT id FROM entities LIMIT 1")
            from argon2 import PasswordHasher

            await conn.execute(
                "INSERT INTO user_profiles (entity_id, email, full_name, "
                "hashed_password, role, is_active, force_password_reset) "
                "VALUES ($1, $2, $3, $4, 'SALES_OPERATOR', TRUE, FALSE)",
                entity_id,
                "sales@test.id",
                "Sales User",
                PasswordHasher().hash("SalesPass1!"),
            )
            await conn.execute(
                "INSERT INTO user_profiles (entity_id, email, full_name, "
                "hashed_password, role, is_active, force_password_reset) "
                "VALUES ($1, $2, $3, $4, 'FINANCE_OPERATOR', TRUE, FALSE)",
                entity_id,
                "finance@test.id",
                "Finance User",
                PasswordHasher().hash("FinPass123!"),
            )
        finally:
            await conn.close()

        # Login as SALES_OPERATOR.
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "sales@test.id", "password": "SalesPass1!"},
        )
        assert resp.status_code == 200, resp.text
        sales_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        # SALES cannot create employees (app-level guard).
        resp = await client.post(
            "/api/v1/hr/employees",
            headers=sales_headers,
            json={
                "employee_code": "EMP-X",
                "full_name": "X",
                "base_salary": "1000000",
                "hire_date": "2024-01-15",
            },
        )
        assert resp.status_code == 403

        # SALES cannot calculate.
        resp = await client.post(
            "/api/v1/hr/payroll/calculate",
            headers=sales_headers,
            json={"employee_id": str(uuid.uuid4()),
                  "payroll_period_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 403

        # FINANCE_OPERATOR cannot approve (Head of F&A only).
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "finance@test.id", "password": "FinPass123!"},
        )
        fin_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        resp = await client.post(
            "/api/v1/hr/payroll/approve",
            headers=fin_headers,
            json={"payroll_period_id": str(uuid.uuid4()),
                  "ap_gaji_account_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_payroll_edge_cases():
    """Duplicate calculate, unprovisioned calendar, wrong-state transitions."""
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Employee + period (no calendar seeded!).
        resp = await client.post(
            "/api/v1/hr/employees",
            headers=headers,
            json={
                "employee_code": "EMP-101",
                "full_name": "Cal Endar",
                "base_salary": "8000000",
                "hire_date": "2024-01-15",
            },
        )
        emp_id = resp.json()["id"]

        resp = await client.post(
            "/api/v1/hr/payroll/periods",
            headers=headers,
            json={
                "period_year": 2026,
                "period_month": 9,
                "start_date": "2026-09-01",
                "end_date": "2026-09-30",
            },
        )
        assert resp.status_code == 201, resp.text
        period_id = resp.json()["id"]

        # 1. Calendar not provisioned -> CALENDAR_NOT_PROVISIONED.
        resp = await client.post(
            "/api/v1/hr/payroll/calculate",
            headers=headers,
            json={"employee_id": emp_id, "payroll_period_id": period_id},
        )
        assert resp.status_code == 422, resp.text
        assert "CALENDAR_NOT_PROVISIONED" in resp.text

        # Seed calendar for Sept, then calculate.
        conn = await asyncpg.connect(TEST_DSN)
        try:
            entity_id = await conn.fetchval("SELECT id FROM entities LIMIT 1")
            await conn.executemany(
                "INSERT INTO company_calendar "
                "(entity_id, calendar_date, is_working_day) "
                "VALUES ($1, $2, TRUE)",
                [
                    (entity_id, date(2026, 9, d))
                    for d in range(1, 31)
                    if date(2026, 9, d).weekday() < 5
                ],
            )
        finally:
            await conn.close()

        resp = await client.post(
            "/api/v1/hr/payroll/calculate",
            headers=headers,
            json={"employee_id": emp_id, "payroll_period_id": period_id},
        )
        assert resp.status_code == 200, resp.text

        # 2. Duplicate calculate -> ENTRY_ALREADY_EXISTS.
        resp = await client.post(
            "/api/v1/hr/payroll/calculate",
            headers=headers,
            json={"employee_id": emp_id, "payroll_period_id": period_id},
        )
        assert resp.status_code == 422, resp.text
        assert "ENTRY_ALREADY_EXISTS" in resp.text

        # 3. Disburse before approve -> PERIOD_NOT_APPROVED.
        resp = await client.post(
            "/api/v1/hr/payroll/disburse",
            headers=headers,
            json={"payroll_period_id": period_id,
                  "kas_bank_account_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 422, resp.text
        assert "PERIOD_NOT_APPROVED" in resp.text

        # 4. Approve with active employees not calculated.
        resp = await client.post(
            "/api/v1/hr/employees",
            headers=headers,
            json={
                "employee_code": "EMP-102",
                "full_name": "Uncal Culated",
                "base_salary": "6000000",
                "hire_date": "2024-01-15",
            },
        )
        resp = await client.post(
            "/api/v1/hr/payroll/approve",
            headers=headers,
            json={"payroll_period_id": period_id,
                  "ap_gaji_account_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 422, resp.text
        assert "INCOMPLETE_CALCULATION" in resp.text
