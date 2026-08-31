"""
Module 4 — Sales & AR integration tests.

Hand-computed scenario (full flow SO -> DO -> Invoice -> Payment):

Setup: warehouse GA; item SKU-Kopi (MA costing, avg 10,000);
accounts: AR 1200, Revenue 4000, PPN Keluaran 2100, Cash 1000,
COGS 5000, Inventory 1100. Customer Toko A: limit 100,000,000,
term 30 days.

S1 Full flow:
  SO-001: 10 kopi @ 15,000 = 150,000 (DRAFT -> CONFIRMED)
  DO: deliver 10 -> issue stock at avg 10,000 -> COGS cost 100,000
  Invoice INV: subtotal 150,000, PPN 11% = 16,500, total 166,500
  GL invoice: Dr AR 166,500 | Cr Revenue 150,000, Cr PPN 16,500
             Dr COGS 100,000 | Cr Inventory 100,000  (balanced 266,500)
  Payment 200,000 (overpay): allocated FIFO 166,500 to INV -> PAID
    GL: Dr Cash 200,000 | Cr AR 166,500 + Cr AR advance 33,500?
    NO: GL payment = Dr Cash 200,000 | Cr AR 200,000 flat (PRD).
    Invoice paid_amount 166,500 status PAID; remaining 33,500
    unallocated (documented overpayment behavior, PRD edge #7).

S2 Credit limit:
  Customer limit 200,000; existing invoice outstanding 166,500
  -> new SO 50,000 confirm -> CREDIT_LIMIT_EXCEEDED (216,500 > 200,000)

S3 Partial delivery:
  SO-002: 10 @ 15,000; deliver 4 -> SO PARTIALLY_DELIVERED;
  deliver 6 more -> DELIVERED; over-deliver -> DELIVERY_EXCEEDS_ORDER

S4 3-way match / invoice-once:
  second invoice from same DO -> DO_ALREADY_INVOICED

S5 POS:
  POS sale 2 kopi @ 20,000 = 40,000; stock issued at 10,000;
  batch posting: Dr Cash 40,000 | Cr Revenue 40,000,
  Dr COGS 20,000 | Cr Inventory 20,000; txn_count 1.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

TEST_DSN = "postgresql://postgres:postgres@localhost:5432/apexledger_test"
ADMIN_EMAIL = "owner@test.id"
ADMIN_PASSWORD = "S3curePass!x"


def _amt(v: str) -> Decimal:
    return Decimal(v)


async def _bootstrap(client: AsyncClient) -> str:
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


async def _seed_accounts() -> dict[str, str]:
    """Seed COA + inventory item + entity GL defaults. Returns ids."""
    accounts = {
        "1000": ("Kas & Bank", "ASSET"),
        "1100": ("Inventory", "ASSET"),
        "1200": ("AR", "ASSET"),
        "2100": ("PPN Keluaran", "LIABILITY"),
        "4000": ("Sales Revenue", "REVENUE"),
        "5000": ("COGS", "EXPENSE"),
    }
    created: dict[str, str] = {}
    conn = await asyncpg.connect(TEST_DSN)
    try:
        entity_id = await conn.fetchval("SELECT id FROM entities LIMIT 1")
        for code, (name, typ) in accounts.items():
            acc_id = await conn.fetchval(
                "INSERT INTO chart_of_accounts "
                "(entity_id, account_code, account_name, account_type, "
                " normal_balance, level, is_postable, is_active) "
                "VALUES ($1, $2, $3, $4, $5, 1, TRUE, TRUE) RETURNING id",
                entity_id, code, name, typ,
                "DEBIT" if typ in ("ASSET", "EXPENSE") else "CREDIT",
            )
            created[code] = str(acc_id)

        # Warehouse + item with GL accounts.
        wh_id = await conn.fetchval(
            "INSERT INTO warehouses (entity_id, code, name) "
            "VALUES ($1, 'GA', 'Gudang A') RETURNING id",
            entity_id,
        )
        item_id = await conn.fetchval(
            "INSERT INTO items (entity_id, item_code, item_name, item_type, "
            "costing_method, uom_base, gl_inventory_account_id, "
            "gl_cogs_account_id) "
            "VALUES ($1, 'SKU-Kopi', 'Kopi Sachet', 'FINISHED_GOOD', "
            "'MOVING_AVERAGE', 'PCS', $2, $3) RETURNING id",
            entity_id, uuid.UUID(created["1100"]),
            uuid.UUID(created["5000"]),
        )
        await conn.execute(
            "INSERT INTO entity_gl_defaults "
            "(entity_id, gl_ar_account_id, gl_sales_revenue_account_id, "
            " gl_ppn_keluaran_account_id, gl_kas_bank_default_account_id) "
            "VALUES ($1, $2, $3, $4, $5)",
            entity_id, uuid.UUID(created["1200"]),
            uuid.UUID(created["4000"]), uuid.UUID(created["2100"]),
            uuid.UUID(created["1000"]),
        )
        created["_wh"] = str(wh_id)
        created["_item"] = str(item_id)
        created["_entity"] = str(entity_id)
    finally:
        await conn.close()
    return created


async def _receive(client, headers, ids, qty="10", cost="10000"):
    resp = await client.post(
        "/api/v1/inv/stock/receive",
        headers=headers,
        json={
            "item_id": ids["_item"], "warehouse_id": ids["_wh"],
            "qty": qty, "unit_cost": cost, "reference_type": "GRN",
        },
    )
    assert resp.status_code == 200, resp.text


async def _mk_customer(client, headers, code, limit, term=30):
    resp = await client.post(
        "/api/v1/sales/customers",
        headers=headers,
        json={
            "customer_code": code, "customer_name": f"Toko {code}",
            "credit_limit": limit, "payment_term_days": term,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _mk_so(client, headers, ids, customer_id, number, qty="10",
                price="15000"):
    resp = await client.post(
        "/api/v1/sales/orders",
        headers=headers,
        json={
            "customer_id": customer_id, "warehouse_id": ids["_wh"],
            "so_number": number, "order_date": "2026-08-31",
            "lines": [{"item_id": ids["_item"], "qty_ordered": qty,
                       "unit_price": price}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _deliver(client, headers, so_json, qty, date_str="2026-08-31"):
    line_id = so_json["lines"][0]["id"]
    resp = await client.post(
        f"/api/v1/sales/orders/{so_json['id']}/delivery-orders",
        headers=headers,
        json={
            "delivery_date": date_str,
            "lines": [{"sales_order_line_id": line_id,
                       "qty_delivered": qty}],
        },
    )
    return resp


@pytest.mark.asyncio
async def _debug_dummy():  # pragma: no cover - helper marker
    pass


@pytest.mark.asyncio
async def test_full_sales_flow_math_proof():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        ids = await _seed_accounts()
        await _receive(client, headers, ids)
        cust = await _mk_customer(client, headers, "CUST-A", "100000000")

        # SO-001
        so = await _mk_so(client, headers, ids, cust, "SO-001")
        assert _amt(so["total_amount"]) == _amt("150000.00")

        # Confirm (credit limit 100M > 150K, ok).
        r = await client.post(
            f"/api/v1/sales/orders/{so['id']}/confirm", headers=headers
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "CONFIRMED"

        # Deliver 10 -> issue at avg 10,000 -> cost 100,000.
        r = await _deliver(client, headers, so, "10")
        assert r.status_code == 200, r.text
        do = r.json()
        assert do["so_status"] == "DELIVERED"

        # Invoice: subtotal 150,000 + PPN 11% 16,500 = 166,500.
        r = await client.post(
            f"/api/v1/sales/delivery-orders/{do['delivery_order_id']}/invoice",
            headers=headers,
            json={"tax_rate_pct": "11"},
        )
        assert r.status_code == 200, r.text
        inv = r.json()
        assert _amt(inv["total_amount"]) == _amt("166500.00")
        assert _amt(inv["cogs"]) == _amt("100000.00")

        # GL balanced: Dr (AR 166,500 + COGS 100,000) = 266,500
        #              Cr (Rev 150,000 + PPN 16,500 + Inv 100,000) = 266,500.
        conn = await asyncpg.connect(TEST_DSN)
        try:
            row = await conn.fetchrow(
                "SELECT SUM(jl.debit_amount) dr, SUM(jl.credit_amount) cr "
                "FROM journal_entries je JOIN journal_lines jl "
                "  ON jl.journal_entry_id = je.id "
                "WHERE je.description LIKE 'Sales Invoice INV-%'"
            )
            assert _amt(str(row["dr"])) == _amt("266500.00")
            assert _amt(str(row["cr"])) == _amt("266500.00")

            # Stock decremented; qty_on_hand 0.
            qty = await conn.fetchval(
                "SELECT qty_on_hand FROM item_warehouse_stock"
            )
            assert _amt(str(qty)) == _amt("0")
        finally:
            await conn.close()

        # Payment 200,000 -> invoice PAID 166,500, surplus 33,500
        # unallocated (PRD edge #7).
        r = await client.post(
            "/api/v1/sales/payments",
            headers=headers,
            json={
                "customer_id": cust, "amount": "200000",
                "payment_date": "2026-09-05",
                "payment_method": "TRANSFER",
            },
        )
        assert r.status_code == 200, r.text
        assert _amt(r.json()["amount"]) == _amt("200000.00")

        conn = await asyncpg.connect(TEST_DSN)
        try:
            inv_row = await conn.fetchrow(
                "SELECT status, paid_amount, total_amount "
                "FROM ar_invoices LIMIT 1"
            )
            assert str(inv_row["status"]) == "PAID"
            assert _amt(str(inv_row["paid_amount"])) == _amt("166500.00")

            # Payment GL: Dr Cash 200,000 | Cr AR 200,000.
            pay_row = await conn.fetchrow(
                "SELECT SUM(jl.debit_amount) dr, SUM(jl.credit_amount) cr "
                "FROM journal_entries je JOIN journal_lines jl "
                "  ON jl.journal_entry_id = je.id "
                "WHERE je.description = 'AR Payment Received'"
            )
            assert _amt(str(pay_row["dr"])) == _amt("200000.00")
            assert _amt(str(pay_row["cr"])) == _amt("200000.00")
        finally:
            await conn.close()


@pytest.mark.asyncio
async def test_credit_limit_exceeded():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        ids = await _seed_accounts()
        await _receive(client, headers, ids)
        # Limit 200,000 — outstanding will be 166,500 after flow.
        cust = await _mk_customer(client, headers, "CUST-A", "200000")

        so = await _mk_so(client, headers, ids, cust, "SO-001")
        r = await client.post(
            f"/api/v1/sales/orders/{so['id']}/confirm", headers=headers
        )
        assert r.status_code == 200, r.text

        r = await _deliver(client, headers, so, "10")
        assert r.status_code == 200, r.text
        do = r.json()
        r = await client.post(
            f"/api/v1/sales/delivery-orders/{do['delivery_order_id']}/invoice",
            headers=headers, json={"tax_rate_pct": "11"},
        )
        assert r.status_code == 200

        # New SO 50,000: 166,500 + 50,000 = 216,500 > 200,000 -> reject.
        so2 = await _mk_so(client, headers, ids, cust, "SO-002")
        r = await client.post(
            f"/api/v1/sales/orders/{so2['id']}/confirm", headers=headers
        )
        assert r.status_code == 422, r.text
        assert "CREDIT_LIMIT_EXCEEDED" in r.text


@pytest.mark.asyncio
async def test_partial_delivery_and_exceed():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        ids = await _seed_accounts()
        await _receive(client, headers, ids)
        cust = await _mk_customer(client, headers, "CUST-A", "100000000")

        so = await _mk_so(client, headers, ids, cust, "SO-001")
        r = await client.post(
            f"/api/v1/sales/orders/{so['id']}/confirm", headers=headers
        )
        assert r.status_code == 200, r.text

        # Deliver 4 of 10 -> PARTIALLY_DELIVERED.
        r = await _deliver(client, headers, so, "4")
        assert r.status_code == 200, r.text
        assert r.json()["so_status"] == "PARTIALLY_DELIVERED"

        # Deliver 6 more -> DELIVERED.
        r = await _deliver(client, headers, so, "6")
        assert r.status_code == 200
        assert r.json()["so_status"] == "DELIVERED"

        # Fully delivered SO can no longer receive DOs.
        r = await _deliver(client, headers, so, "1")
        assert r.status_code == 422
        assert "SO_INVALID_STATUS" in r.text

        # Over-delivery on a fresh SO -> DELIVERY_EXCEEDS_ORDER.
        so2 = await _mk_so(client, headers, ids, cust, "SO-002")
        r = await client.post(
            f"/api/v1/sales/orders/{so2['id']}/confirm", headers=headers
        )
        assert r.status_code == 200, r.text
        r = await _deliver(client, headers, so2, "11")
        assert r.status_code == 422, r.text
        assert "DELIVERY_EXCEEDS_ORDER" in r.text


@pytest.mark.asyncio
async def test_double_invoice_rejected():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        ids = await _seed_accounts()
        await _receive(client, headers, ids)
        cust = await _mk_customer(client, headers, "CUST-A", "100000000")

        so = await _mk_so(client, headers, ids, cust, "SO-001")
        r = await client.post(
            f"/api/v1/sales/orders/{so['id']}/confirm", headers=headers
        )
        assert r.status_code == 200, r.text
        r = await _deliver(client, headers, so, "10")
        assert r.status_code == 200, r.text
        do = r.json()

        r = await client.post(
            f"/api/v1/sales/delivery-orders/{do['delivery_order_id']}/invoice",
            headers=headers, json={"tax_rate_pct": "11"},
        )
        assert r.status_code == 200, r.text

        # Second invoice for the same DO -> rejected (status check fires
        # first: DO became INVOICED, which also blocks re-invoicing).
        r = await client.post(
            f"/api/v1/sales/delivery-orders/{do['delivery_order_id']}/invoice",
            headers=headers, json={"tax_rate_pct": "11"},
        )
        assert r.status_code == 422, r.text
        assert ("DO_ALREADY_INVOICED" in r.text
                or "DO_INVALID_STATUS" in r.text)


@pytest.mark.asyncio
async def test_pos_sale_and_batch_posting():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        ids = await _seed_accounts()
        await _receive(client, headers, ids)

        # POS: 2 kopi @ 20,000 = 40,000; COGS 2 x 10,000 = 20,000.
        r = await client.post(
            "/api/v1/sales/pos",
            headers=headers,
            json={
                "warehouse_id": ids["_wh"], "payment_method": "CASH",
                "lines": [{"item_id": ids["_item"], "qty": "2",
                           "unit_price": "20000"}],
            },
        )
        assert r.status_code == 200, r.text
        pos = r.json()
        assert _amt(pos["total_amount"]) == _amt("40000.00")
        assert _amt(pos["total_cogs"]) == _amt("20000.00")

        # Batch posting: 1 txn -> Dr Cash 40,000 | Cr Rev 40,000,
        # Dr COGS 20,000 | Cr Inv 20,000.
        r = await client.post(
            "/api/v1/sales/pos/post-batch", headers=headers
        )
        assert r.status_code == 200, r.text
        batch = r.json()
        assert batch["txn_count"] == 1
        assert _amt(batch["total_sales"]) == _amt("40000.00")
        assert _amt(batch["total_cogs"]) == _amt("20000.00")

        conn = await asyncpg.connect(TEST_DSN)
        try:
            row = await conn.fetchrow(
                "SELECT SUM(jl.debit_amount) dr, SUM(jl.credit_amount) cr "
                "FROM journal_entries je JOIN journal_lines jl "
                "  ON jl.journal_entry_id = je.id "
                "WHERE je.description LIKE 'POS Batch Posting%'"
            )
            assert _amt(str(row["dr"])) == _amt("60000.00")
            assert _amt(str(row["cr"])) == _amt("60000.00")

            # Second batch call: nothing left.
            r2 = await client.post(
                "/api/v1/sales/pos/post-batch", headers=headers
            )
            assert r2.json()["txn_count"] == 0
        finally:
            await conn.close()
