"""
Module 5A — Purchase Return (Debit Note) & Landed Cost tests.

Scenario A (purchase return math proof):
  Prior stock: 10 units @ 10,000 (avg 10,000).
  PO: 10 units @ 10,000 -> approve -> GRN receive 10 -> inspect
  10 accepted, 0 rejected -> stock 20 @ avg 10,000 (PO price).
  Bill 10 @ 10,000 + PPN 11% 11,000 = 111,000 -> match APPROVED.
  Purchase return: 2 units rusak @ 10,000 = 20,000.
    -> approve: stock 20 -> 18, avg_cost invariant 10,000
       subtotal 20,000, PPN 2,200, total 22,200
       GL debit note: Dr AP 22,200 = Cr Inventory 20,000
                      + Cr PPN Masukan 2,200
       AP bill paid_amount 22,200 (outstanding 111,000-22,200).

Scenario B (landed cost math proof):
  Same setup as A but no return; instead allocate freight
  LC-001 5,000 BY_QTY on the GRN (10 accepted units):
    -> 1 line, allocated 5,000
    -> avg_cost: (10,000*20 + 5,000)/20 = 10,250 (stock 20)
    -> GL: Dr Inventory 5,000 = Cr LC Clearing 5,000
    -> status ALLOCATED; double allocate rejected.

Edge cases: return qty > accepted; double approve return;
allocate on non-COMPLETED GRN; double allocate LC.
"""

from __future__ import annotations

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from tests.test_procurement import (
    _amt,
    _mk_po,
    _mk_vendor,
    _seed_procurement_accounts,
)
from tests.test_sales import _bootstrap, _receive, _seed_accounts

DB = "postgresql://postgres:postgres@localhost:5432/apexledger_test"


async def _grn_ready(client, headers, ids, vendor, accept="10"):
    """PO -> submit -> approve -> receive 10 -> inspect accept."""
    po = await _mk_po(client, headers, ids, vendor, "PO-001")
    r = await client.post(
        f"/api/v1/proc/orders/{po['id']}/submit", headers=headers
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/v1/proc/orders/{po['id']}/approve", headers=headers
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/v1/proc/orders/{po['id']}/receive",
        headers=headers,
        json={
            "received_date": "2026-09-02",
            "lines": [
                {
                    "purchase_order_line_id": po["lines"][0]["id"],
                    "qty_received": "10",
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    grn = r.json()

    conn = await asyncpg.connect(DB)
    try:
        grn_line = await conn.fetchrow(
            "SELECT id FROM grn_lines WHERE grn_id = $1",
            grn["grn_id"],
        )
        grn_line_id = str(grn_line["id"])
    finally:
        await conn.close()

    r = await client.post(
        f"/api/v1/proc/grns/{grn['grn_id']}/inspect",
        headers=headers,
        json={
            "line_results": [
                {
                    "grn_line_id": grn_line_id,
                    "qty_accepted": accept,
                    "qty_rejected": str(10 - int(accept)),
                }
            ]
        },
    )
    assert r.status_code == 200, r.text
    return {"po": po, "grn": grn, "grn_line_id": grn_line_id}


async def _bill_and_match(client, headers, ids, grn_id,
                           price="10000", qty="10"):
    r = await client.post(
        "/api/v1/proc/bills",
        headers=headers,
        json={
            "grn_id": grn_id,
            "bill_number": "BILL-001",
            "bill_date": "2026-09-03",
            "tax_rate_pct": "11",
            "lines": [
                {
                    "item_id": ids["_item"],
                    "qty": qty,
                    "unit_price": price,
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    bill = r.json()
    r = await client.post(
        f"/api/v1/proc/bills/{bill['ap_bill_id']}/match",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APPROVED", r.text
    return bill


@pytest.mark.asyncio
async def test_purchase_return_math_proof():
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

        flow = await _grn_ready(client, headers, ids, vendor)
        await _bill_and_match(
            client, headers, ids, flow["grn"]["grn_id"]
        )

        # Stock is 20 @ avg 10,000 now.
        r = await client.post(
            "/api/v1/proc/returns",
            headers=headers,
            json={
                "vendor_id": vendor["id"],
                "grn_id": flow["grn"]["grn_id"],
                "warehouse_id": ids["_wh"],
                "return_number": "PR-001",
                "return_date": "2026-09-05",
                "reason": "2 unit rusak saat QC ulang",
                "lines": [
                    {
                        "grn_line_id": flow["grn_line_id"],
                        "item_id": ids["_item"],
                        "qty_returned": "2",
                        "unit_price": "10000",
                    }
                ],
            },
        )
        assert r.status_code == 201, r.text
        ret_id = r.json()["id"]

        r = await client.post(
            f"/api/v1/proc/returns/{ret_id}/approve",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert _amt(body["subtotal"]) == _amt("20000")
        assert _amt(body["tax_amount"]) == _amt("2200")
        assert _amt(body["total_amount"]) == _amt("22200")

        conn = await asyncpg.connect(DB)
        try:
            # Stock: 20 - 2 = 18, avg invariant 10,000.
            row = await conn.fetchrow(
                "SELECT qty_on_hand, avg_cost "
                "FROM item_warehouse_stock"
            )
            assert _amt(row["qty_on_hand"]) == _amt("18")
            assert _amt(row["avg_cost"]) == _amt("10000")

            # GL: Dr AP 22,200 = Cr Inv 20,000 + Cr PPN 2,200.
            row = await conn.fetchrow(
                "SELECT SUM(jl.debit_amount) dr, "
                "SUM(jl.credit_amount) cr "
                "FROM journal_entries je "
                "JOIN journal_lines jl "
                " ON jl.journal_entry_id = je.id "
                "WHERE je.description LIKE "
                " 'Purchase Return / Debit Note%'"
            )
            assert _amt(row["dr"]) == _amt("22200")
            assert _amt(row["cr"]) == _amt("22200")

            # AP bill reduced: 111,000 paid 22,200.
            bill = await conn.fetchrow(
                "SELECT total_amount, paid_amount "
                "FROM ap_bills LIMIT 1"
            )
            assert _amt(bill["total_amount"]) == _amt("111000")
            assert _amt(bill["paid_amount"]) == _amt("22200")
        finally:
            await conn.close()


@pytest.mark.asyncio
async def test_landed_cost_math_proof():
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

        flow = await _grn_ready(client, headers, ids, vendor)

        # Add a landed cost clearing account + update defaults.
        conn = await asyncpg.connect(DB)
        try:
            entity_id = await conn.fetchval(
                "SELECT entity_id FROM user_profiles LIMIT 1"
            )
            acc_id = await conn.fetchval(
                "INSERT INTO chart_of_accounts "
                "(entity_id, account_code, account_name, "
                " account_type, normal_balance, level, "
                " is_postable, is_active) "
                "VALUES ($1, '1400', 'Landed Cost Clearing', "
                " 'ASSET', 'DEBIT', 1, TRUE, TRUE) RETURNING id",
                entity_id,
            )
            await conn.execute(
                "UPDATE entity_gl_defaults SET "
                "gl_landed_cost_clearing_account_id = $1 "
                "WHERE entity_id = $2",
                acc_id, entity_id,
            )
        finally:
            await conn.close()

        r = await client.post(
            "/api/v1/proc/landed-costs",
            headers=headers,
            json={
                "grn_id": flow["grn"]["grn_id"],
                "lc_number": "LC-001",
                "lc_date": "2026-09-06",
                "description": "Freight kontainer import",
                "total_amount": "5000",
                "allocation_method": "BY_QTY",
            },
        )
        assert r.status_code == 201, r.text
        lc_id = r.json()["id"]

        r = await client.post(
            f"/api/v1/proc/landed-costs/{lc_id}/allocate",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert _amt(body["total_allocated"]) == _amt("5000")
        assert body["lines_count"] == 1

        conn = await asyncpg.connect(DB)
        try:
            # avg_cost: (10,000 * 20 + 5,000) / 20 = 10,250.
            row = await conn.fetchrow(
                "SELECT qty_on_hand, avg_cost "
                "FROM item_warehouse_stock"
            )
            assert _amt(row["qty_on_hand"]) == _amt("20")
            assert _amt(row["avg_cost"]) == _amt("10250")

            # GL: Dr Inventory 5,000 = Cr LC Clearing 5,000.
            row = await conn.fetchrow(
                "SELECT SUM(jl.debit_amount) dr, "
                "SUM(jl.credit_amount) cr "
                "FROM journal_entries je "
                "JOIN journal_lines jl "
                " ON jl.journal_entry_id = je.id "
                "WHERE je.description LIKE "
                " 'Landed Cost Allocation%'"
            )
            assert _amt(row["dr"]) == _amt("5000")
            assert _amt(row["cr"]) == _amt("5000")
        finally:
            await conn.close()

        # Double allocate rejected.
        r = await client.post(
            f"/api/v1/proc/landed-costs/{lc_id}/allocate",
            headers=headers,
        )
        assert r.status_code == 422, r.text
        assert "LC_INVALID_STATUS" in r.text


@pytest.mark.asyncio
async def test_return_guards():
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

        flow = await _grn_ready(client, headers, ids, vendor)

        # Return qty 11 > accepted 10 -> rejected on approve.
        r = await client.post(
            "/api/v1/proc/returns",
            headers=headers,
            json={
                "vendor_id": vendor["id"],
                "grn_id": flow["grn"]["grn_id"],
                "warehouse_id": ids["_wh"],
                "return_number": "PR-001",
                "return_date": "2026-09-05",
                "reason": "Salah pesan jumlah",
                "lines": [
                    {
                        "grn_line_id": flow["grn_line_id"],
                        "item_id": ids["_item"],
                        "qty_returned": "11",
                        "unit_price": "10000",
                    }
                ],
            },
        )
        assert r.status_code == 201, r.text
        ret_id = r.json()["id"]

        r = await client.post(
            f"/api/v1/proc/returns/{ret_id}/approve",
            headers=headers,
        )
        assert r.status_code == 422, r.text
        assert "RETURN_QTY_EXCEEDS_ACCEPTED" in r.text

        # LC on a GRN that is COMPLETED is fine; but allocate LC
        # twice or on non-DRAFT must fail — covered by creating a
        # second LC on the same GRN then allocating both is OK
        # (separate LC numbers are separate documents).
        # Double approve of the same return is rejected above via
        # status check: approve the corrected return then retry.
        r = await client.post(
            "/api/v1/proc/returns",
            headers=headers,
            json={
                "vendor_id": vendor["id"],
                "grn_id": flow["grn"]["grn_id"],
                "warehouse_id": ids["_wh"],
                "return_number": "PR-002",
                "return_date": "2026-09-05",
                "reason": "2 unit rusak",
                "lines": [
                    {
                        "grn_line_id": flow["grn_line_id"],
                        "item_id": ids["_item"],
                        "qty_returned": "2",
                        "unit_price": "10000",
                    }
                ],
            },
        )
        assert r.status_code == 201, r.text
        ret2 = r.json()["id"]

        r = await client.post(
            f"/api/v1/proc/returns/{ret2}/approve",
            headers=headers,
        )
        assert r.status_code == 200, r.text

        r = await client.post(
            f"/api/v1/proc/returns/{ret2}/approve",
            headers=headers,
        )
        assert r.status_code == 422, r.text
        assert "RETURN_INVALID_STATUS" in r.text


@pytest.mark.asyncio
async def test_landed_cost_guards():
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

        # GRN not inspected yet (DRAFT) -> LC allocate must fail
        # with GRN_NOT_COMPLETED.
        po = await _mk_po(client, headers, ids, vendor, "PO-001")
        r = await client.post(
            f"/api/v1/proc/orders/{po['id']}/submit", headers=headers
        )
        assert r.status_code == 200, r.text
        r = await client.post(
            f"/api/v1/proc/orders/{po['id']}/approve", headers=headers
        )
        assert r.status_code == 200, r.text
        r = await client.post(
            f"/api/v1/proc/orders/{po['id']}/receive",
            headers=headers,
            json={
                "received_date": "2026-09-02",
                "lines": [
                    {
                        "purchase_order_line_id": po["lines"][0]["id"],
                        "qty_received": "10",
                    }
                ],
            },
        )
        assert r.status_code == 200, r.text
        grn = r.json()

        r = await client.post(
            "/api/v1/proc/landed-costs",
            headers=headers,
            json={
                "grn_id": grn["grn_id"],
                "lc_number": "LC-001",
                "lc_date": "2026-09-06",
                "description": "Freight",
                "total_amount": "5000",
                "allocation_method": "BY_VALUE",
            },
        )
        assert r.status_code == 201, r.text
        lc_id = r.json()["id"]

        r = await client.post(
            f"/api/v1/proc/landed-costs/{lc_id}/allocate",
            headers=headers,
        )
        assert r.status_code == 422, r.text
        assert "GRN_NOT_COMPLETED" in r.text
