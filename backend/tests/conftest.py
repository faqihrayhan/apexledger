"""
Pytest global configuration: isolated test database per session.

Runs BEFORE any test module imports the app:
1. Points ``APEX_DATABASE_URL`` at a dedicated ``apexledger_test`` database.
2. Drops & recreates that database for a clean slate.
3. Applies all Alembic migrations (schema + RLS + seed data).

Each test gets its tables truncated via the autouse ``clean_tables``
fixture (using a *fresh* asyncpg connection — pooled connections are
loop-bound and cannot be reused across pytest-asyncio event loops),
and the app engine pool is disposed so every test starts with a
fresh connection pool.
"""

import asyncio
import os
import subprocess

import asyncpg
import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["APEX_DATABASE_URL"] = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/apexledger_test"
)

ADMIN_DSN = "postgresql://postgres:postgres@localhost:5432/postgres"
TEST_DSN = "postgresql://postgres:postgres@localhost:5432/apexledger_test"


async def _reset_test_database() -> None:
    """Drop and recreate the test database (fresh slate per session)."""
    conn = await asyncpg.connect(ADMIN_DSN)
    try:
        await conn.execute("DROP DATABASE IF EXISTS apexledger_test WITH (FORCE)")
        await conn.execute("CREATE DATABASE apexledger_test")
    finally:
        await conn.close()


asyncio.run(_reset_test_database())

subprocess.run(
    ["alembic", "upgrade", "head"],
    check=True,
    cwd=BACKEND_DIR,
    env={**os.environ},  # inherits APEX_DATABASE_URL -> test database
)


@pytest.fixture(autouse=True)
async def clean_tables():
    """After each test: truncate data tables and reset the app engine pool.

    A raw asyncpg connection is used for the TRUNCATE because pooled
    engine connections are bound to the event loop of the test that
    created them — reusing them across pytest-asyncio's per-test loops
    raises ``Future attached to a different loop``.
    """
    yield

    conn = await asyncpg.connect(TEST_DSN)
    try:
        # NOTE: CASCADE also wipes payroll_component_master and
        # bpjs_rate_config (FK chains to entities); re-seed them so every
        # test starts with the migration-provided config rows.
        await conn.execute(
            "TRUNCATE TABLE employee_productivity_metrics, "
            "budget_revisions, budget_lines, budgets, "
            "asset_disposals, "
            "asset_depreciation_schedule, fixed_assets, "
            "cash_flow_forecast_lines, "
            "bank_statement_lines, "
            "kasbon_settlement_lines, kasbon_settlements, "
            "kasbon_requests, petty_cash_funds, bank_accounts, "
            "landed_cost_lines, landed_costs, "
            "ap_payment_allocations, ap_payments, "
            "ap_bill_lines, ap_bills, grn_lines, "
            "goods_received_notes, purchase_order_lines, "
            "purchase_orders, purchase_request_lines, "
            "purchase_requests, vendors, approval_thresholds, "
            "sales_return_lines, sales_returns, "
            "pos_transaction_lines, pos_transactions, "
            "ar_payment_allocations, ar_payments, ar_invoice_lines, "
            "ar_invoices, delivery_order_lines, delivery_orders, "
            "sales_order_lines, sales_orders, customers, "
            "entity_gl_defaults, "
            "stock_transactions, item_warehouse_stock, "
            "stock_lots, work_orders, cost_centers, bom_components, boms, "
            "items, warehouses, "
            "payroll_entry_lines, payroll_entries, "
            "payroll_periods, attendance_records, company_calendar, "
            "employees, overtime_multiplier_config, "
            "journal_lines, journal_entries, "
            "fiscal_periods, fiscal_years, system_logs, "
            "user_profiles, entities CASCADE"
        )
        await conn.execute(
            "INSERT INTO payroll_component_master "
            "(code, name, type, is_taxable) VALUES "
            "('BASIC', 'Gaji Pokok', 'EARNING', TRUE), "
            "('OVERTIME', 'Upah Lembur', 'EARNING', TRUE), "
            "('INCENTIVE', 'Insentif', 'EARNING', TRUE), "
            "('BPJS_KES_EE', 'BPJS Kesehatan (Pegawai)', 'DEDUCTION', FALSE), "
            "('BPJS_JHT_EE', 'BPJS JHT (Pegawai)', 'DEDUCTION', FALSE), "
            "('BPJS_JP_EE', 'BPJS Jaminan Pensiun (Pegawai)', 'DEDUCTION', FALSE), "
            "('PPH21', 'PPh 21 (TER)', 'DEDUCTION', FALSE), "
            "('DENDA_UNPAID', 'Potongan Hari Tidak Masuk', 'DEDUCTION', FALSE), "
            "('DENDA_LATE', 'Potongan Keterlambatan', 'DEDUCTION', FALSE)"
        )
        await conn.execute(
            "INSERT INTO bpjs_rate_config "
            "(component_code, employee_rate_pct, employer_rate_pct, "
            "salary_cap, effective_date) VALUES "
            "('BPJS_KES_EE', 1.0, 4.0, 12000000, DATE '2024-01-01'), "
            "('BPJS_JHT_EE', 2.0, 3.7, NULL, DATE '2024-01-01'), "
            "('BPJS_JP_EE', 1.0, 2.0, 10547400, DATE '2025-01-01')"
        )
    finally:
        await conn.close()

    # Dispose the app engine pool so the next test gets a fresh pool
    # bound to its own event loop.
    from app.db.session import engine

    await engine.dispose()
