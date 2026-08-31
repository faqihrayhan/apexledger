"""
Module 4A — Sales Return / Credit Note integration tests.

Scenario (extends the Module 4 flow):
  Invoice: 10 kopi @ 15,000 = 150,000 + PPN 11% 16,500 = 166,500
  Return 3 kopi (reason: rusak):
    subtotal = 3 x 15,000 = 45,000
    tax rate derived from invoice = 16,500/150,000 = 11%
    tax = 4,950.00
    credit note total = 49,950.00
  Stock back: 3 @ avg_cost 10,000 -> qty_on_hand 3 again
  COGS reversal: 3 x 10,000 = 30,000 (Dr Inventory / Cr COGS)
  GL (balanced 129,900 = 129,900):
    Dr Sales Return 45,000 | Dr PPN 4,950 | Cr AR 49,950
    Dr Inventory 30,000 | Cr COGS 30,000
  AR cut: paid_amount 0 -> 49,950; status ISSUED (49,950 < 166,500)

Edge cases:
  - return 11 (> qty invoice 10) -> RETURN_QTY_EXCEEDS_INVOICE
  - approve twice -> RETURN_INVALID_STATUS
"""

from __future__ import annotations

from decimal import Decimal

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from tests.test_sales import (
    _bootstrap,
    _mk_customer,
    _mk_so,
    _receive,
    _seed_accounts,
)


def _amt(v: str) -> Decimal:
    return Decimal(v)


async def _flow_to_invoice(client, headers, ids) -> dict:
    """Run the base flow: SO -> confirm -> DO -> invoice."""
    cust = await _mk_customer(client, headers, "CUST-A", "100000000")
    so = await _mk_so(client, headers, ids, cust, "SO-001")
    r = await client.post(
        f"/api/v1/sales/orders/{so['id']}/confirm", headers=headers
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/v1/sales/orders/{so['id']}/delivery-orders",
        headers=headers,
        json={
            "delivery_date": "2026-08-31",
            "lines": [
                {
                    "sales_order_line_id": so["lines"][0]["id"],
                    "qty_delivered": "10",
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    do_id = r.json()["delivery_order_id"]
    r = await client.post(
        f"/api/v1/sales/delivery-orders/{do_id}/invoice",
        headers=headers, json={"tax_rate_pct": "11"},
    )
    assert r.status_code == 200, r.text
    return {"cust": cust, "invoice": r.json()}


async def _mk_return(client, headers, ids, inv, number, qty="3") -> dict:
    conn = await asyncpg.connect(
        "postgresql://postgres:postgres@localhost:5432/apexledger_test"
    )
    try:
        inv_line = await conn.fetchrow(
            "SELECT id, item_id, qty, unit_price FROM ar_invoice_lines LIMIT 1"
        )
        inv_row = await conn.fetchrow(
            "SELECT id, customer_id FROM ar_invoices "
            "WHERE invoice_number = $1", inv["invoice_number"],
        )
    finally:
        await conn.close()

    line_total = str(_amt(qty) * _amt("15000"))
    r = await client.post(
        "/api/v1/sales/returns",
        headers=headers,
        json={
            "customer_id": str(inv_row["customer_id"]),
            "ar_invoice_id": str(inv_row["id"]),
            "warehouse_id": ids["_wh"],
            "return_number": number,
            "return_date": "2026-09-02",
            "reason": "Barang rusak",
            "lines": [
                {
                    "ar_invoice_line_id": str(inv_line["id"]),
                    "item_id": str(inv_line["item_id"]),
                    "qty_returned": qty,
                    "unit_price": str(inv_line["unit_price"]),
                    "line_total": line_total,
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_sales_return_full_math_proof():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        ids = await _seed_accounts()
        await _receive(client, headers, ids)
        flow = await _flow_to_invoice(client, headers, ids)

        ret = await _mk_return(client, headers, ids, flow["invoice"],
                               "SR-0001", "3")
        assert ret["status"] == "DRAFT"

        # Approve.
        r = await client.post(
            f"/api/v1/sales/returns/{ret['id']}/approve", headers=headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # 3 x 15,000 = 45,000; tax 11% = 4,950; total 49,950.
        assert _amt(body["total_amount"]) == _amt("49950.00")
        assert _amt(body["cogs_reversed"]) == _amt("30000.00")

        conn = await asyncpg.connect(
            "postgresql://postgres:postgres@localhost:5432/apexledger_test"
        )
        try:
            # Stock back: 3 units in the warehouse again.
            qty = await conn.fetchval(
                "SELECT qty_on_hand FROM item_warehouse_stock"
            )
            assert _amt(str(qty)) == _amt("3")

            # GL balanced: Dr (45,000 + 4,950 + 30,000) = Cr (49,950
            # + 30,000) = 79,950.
            row = await conn.fetchrow(
                "SELECT SUM(jl.debit_amount) dr, SUM(jl.credit_amount) cr "
                "FROM journal_entries je JOIN journal_lines jl "
                "  ON jl.journal_entry_id = je.id "
                "WHERE je.description LIKE 'Sales Return / Credit Note%'"
            )
            assert _amt(str(row["dr"])) == _amt("79950.00")
            assert _amt(str(row["cr"])) == _amt("79950.00")

            # AR cut: paid 49,950 of 166,500 -> still ISSUED.
            inv_row = await conn.fetchrow(
                "SELECT paid_amount, status FROM ar_invoices"
            )
            assert _amt(str(inv_row["paid_amount"])) == _amt("49950.00")
            assert str(inv_row["status"]) == "ISSUED"

            # Return status APPROVED.
            ret_row = await conn.fetchrow(
                "SELECT status FROM sales_returns"
            )
            assert str(ret_row["status"]) == "APPROVED"
        finally:
            await conn.close()


@pytest.mark.asyncio
async def test_return_qty_exceeds_invoice():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        ids = await _seed_accounts()
        await _receive(client, headers, ids)
        flow = await _flow_to_invoice(client, headers, ids)

        ret = await _mk_return(client, headers, ids, flow["invoice"],
                               "SR-0001", "11")
        r = await client.post(
            f"/api/v1/sales/returns/{ret['id']}/approve", headers=headers
        )
        assert r.status_code == 422, r.text
        assert "RETURN_QTY_EXCEEDS_INVOICE" in r.text


@pytest.mark.asyncio
async def test_double_approve_rejected():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        ids = await _seed_accounts()
        await _receive(client, headers, ids)
        flow = await _flow_to_invoice(client, headers, ids)

        ret = await _mk_return(client, headers, ids, flow["invoice"],
                               "SR-0001", "3")
        r = await client.post(
            f"/api/v1/sales/returns/{ret['id']}/approve", headers=headers
        )
        assert r.status_code == 200, r.text

        r = await client.post(
            f"/api/v1/sales/returns/{ret['id']}/approve", headers=headers
        )
        assert r.status_code == 422, r.text
        assert "RETURN_INVALID_STATUS" in r.text
