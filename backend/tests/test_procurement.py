"""
Module 5 — Procurement & AP (PUTG) integration tests.

Scenario A (full happy path):
  Item kopi (avg 10,000 after prior receive). PO: 10 units @ 10,000
  = 100,000. Approval threshold: PO >= 50,000,000 needs DIREKSI;
  below that DEPT_HEAD_FA (via approval_thresholds seed).
  -> submit -> PENDING_APPROVAL (required role from engine)
  -> approve by FINANCE admin (SUPER_ADMIN bootstrap)
  -> receive 10 (GRN DRAFT, stock NOT moved yet)
  -> inspect: 8 accepted, 2 rejected (rusak)
       stock: 10 + 8 = 18 units; avg recompute with @10,000
       GL: Dr Inventory 80,000 / Cr GR/IR 80,000 (PO price)
       PO -> PARTIALLY_RECEIVED (8 < 10)
       GRN -> PARTIAL
  -> bill 8 @ 10,000 = 80,000 + PPN 8,800 = 88,800
  -> 3-way match OK (qty 8 <= accepted 8, price == PO)
       GL: Dr GR/IR 80,000, Dr PPN Masukan 8,800 / Cr AP 88,800
  -> AP payment 88,800 -> bill PAID
       GL: Dr AP 88,800 / Cr Kas 88,800

Scenario B (3-way mismatch -> DISPUTED):
  Same setup but bill at 10,500 (5% > 2% tolerance) -> DISPUTED
  with reason; no GL posted.

Scenario C (approve authority):
  PO below threshold -> required DEPT_HEAD_FA (default).

Edge cases: over-receipt, inspect twice, bill from PENDING GRN,
double bill per GRN, double submit.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from tests.test_sales import (
    _bootstrap,
    _receive,
    _seed_accounts,
)

DB = "postgresql://postgres:postgres@localhost:5432/apexledger_test"


async def _seed_procurement_accounts(ids) -> None:
    """Add AP-side accounts + update entity_gl_defaults (Module 5)."""
    conn = await asyncpg.connect(DB)
    try:
        entity_id = uuid.UUID(ids["_entity"])
        accounts = {
            "1300": ("GR/IR Clearing", "ASSET"),
            "2000": ("AP Vendor Payable", "LIABILITY"),
            "2200": ("PPN Masukan", "ASSET"),
            "5900": ("Purchase Price Variance", "EXPENSE"),
        }
        created: dict[str, str] = {}
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
        await conn.execute(
            "UPDATE entity_gl_defaults SET "
            "  gl_ap_account_id = $1, "
            "  gl_ppn_masukan_account_id = $2, "
            "  gl_grir_clearing_account_id = $3, "
            "  gl_price_variance_account_id = $4 "
            "WHERE entity_id = $5",
            uuid.UUID(created["2000"]),
            uuid.UUID(created["2200"]),
            uuid.UUID(created["1300"]),
            uuid.UUID(created["5900"]),
            entity_id,
        )
    finally:
        await conn.close()


def _amt(v) -> Decimal:
    return Decimal(str(v))


async def _setup_item_and_warehouse(client, headers, ids):
    """Ensure item exists with inventory accounts; returns wh id."""
    return ids["_wh"], ids["_item"]


async def _mk_vendor(client, headers, code="VEND-A") -> dict:
    r = await client.post(
        "/api/v1/proc/vendors",
        headers=headers,
        json={
            "vendor_code": code,
            "vendor_name": "PT Sumber Kopi",
            "payment_term_days": 30,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _mk_po(client, headers, ids, vendor, number,
                 qty="10", price="10000") -> dict:
    r = await client.post(
        "/api/v1/proc/orders",
        headers=headers,
        json={
            "vendor_id": vendor["id"],
            "warehouse_id": ids["_wh"],
            "po_number": number,
            "order_date": "2026-09-01",
            "lines": [
                {
                    "item_id": ids["_item"],
                    "qty_ordered": qty,
                    "unit_price": price,
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _full_flow_to_match(client, headers, ids, vendor,
                              bill_price="10000") -> dict:
    """PO -> submit -> approve -> receive -> inspect 8/2 -> bill.

    Returns dict with grn_id, bill response json.
    """
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
            "SELECT id FROM grn_lines WHERE grn_id = $1", grn["grn_id"]
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
                    "qty_accepted": "8",
                    "qty_rejected": "2",
                }
            ]
        },
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        "/api/v1/proc/bills",
        headers=headers,
        json={
            "grn_id": grn["grn_id"],
            "bill_number": "BILL-001",
            "bill_date": "2026-09-03",
            "tax_rate_pct": "11",
            "lines": [
                {
                    "item_id": ids["_item"],
                    "qty": "8",
                    "unit_price": bill_price,
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    return {"grn": grn, "bill": r.json(), "po": po}


@pytest.mark.asyncio
async def test_procurement_full_flow_math_proof():
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

        # Seed an approval threshold: PO >= 50,000,000 -> DIREKSI
        conn = await asyncpg.connect(DB)
        try:
            entity_id = await conn.fetchval(
                "SELECT entity_id FROM user_profiles LIMIT 1"
            )
            await conn.execute(
                "INSERT INTO approval_thresholds "
                "(entity_id, document_type, min_amount, required_role) "
                "VALUES ($1, 'PO', 50000000, 'DIREKSI')",
                entity_id,
            )
        finally:
            await conn.close()

        flow = await _full_flow_to_match(
            client, headers, ids, vendor, bill_price="10000"
        )

        # 3-way match -> APPROVED + GL.
        r = await client.post(
            f"/api/v1/proc/bills/{flow['bill']['ap_bill_id']}/match",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "APPROVED"
        assert _amt(r.json()["price_variance"]) == _amt("0")

        # AP payment 88,800 -> PAID.
        r = await client.post(
            "/api/v1/proc/payments",
            headers=headers,
            json={
                "vendor_id": vendor["id"],
                "payment_date": "2026-09-10",
                "amount": "88800",
                "payment_method": "TRANSFER",
            },
        )
        assert r.status_code == 201, r.text

        conn = await asyncpg.connect(DB)
        try:
            # Bill fully paid.
            bill = await conn.fetchrow(
                "SELECT status, paid_amount, total_amount "
                "FROM ap_bills LIMIT 1"
            )
            assert str(bill["status"]) == "PAID"
            assert _amt(bill["paid_amount"]) == _amt("88800")

            # GL checks: GRN inspection + bill match + payment.
            # Inspection: Dr Inventory 80,000 / Cr GR/IR 80,000.
            row = await conn.fetchrow(
                "SELECT SUM(jl.debit_amount) dr, "
                "SUM(jl.credit_amount) cr "
                "FROM journal_entries je JOIN journal_lines jl "
                " ON jl.journal_entry_id = je.id "
                "WHERE je.description LIKE 'GRN Inspection%'"
            )
            assert _amt(row["dr"]) == _amt("80000.00")
            assert _amt(row["cr"]) == _amt("80000.00")

            # Bill match: Dr 88,800 = Cr 88,800
            # (GR/IR 80,000 + PPN 8,800 / AP 88,800).
            row = await conn.fetchrow(
                "SELECT SUM(jl.debit_amount) dr, "
                "SUM(jl.credit_amount) cr "
                "FROM journal_entries je JOIN journal_lines jl "
                " ON jl.journal_entry_id = je.id "
                "WHERE je.description LIKE 'AP Bill Matched%'"
            )
            assert _amt(row["dr"]) == _amt("88800.00")
            assert _amt(row["cr"]) == _amt("88800.00")

            # Payment: Dr AP 88,800 / Cr Kas 88,800.
            row = await conn.fetchrow(
                "SELECT SUM(jl.debit_amount) dr, "
                "SUM(jl.credit_amount) cr "
                "FROM journal_entries je JOIN journal_lines jl "
                " ON jl.journal_entry_id = je.id "
                "WHERE je.description LIKE 'AP Payment%'"
            )
            assert _amt(row["dr"]) == _amt("88800.00")
            assert _amt(row["cr"]) == _amt("88800.00")

            # Stock: 10 (initial receive) + 8 accepted = 18.
            qty = await conn.fetchval(
                "SELECT qty_on_hand FROM item_warehouse_stock"
            )
            assert _amt(qty) == _amt("18")

            # PO status: PARTIALLY_RECEIVED (8 accepted < 10).
            po_status = await conn.fetchval(
                "SELECT status FROM purchase_orders"
            )
            assert str(po_status) == "PARTIALLY_RECEIVED"
        finally:
            await conn.close()


@pytest.mark.asyncio
async def test_three_way_match_disputed():
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

        flow = await _full_flow_to_match(
            client, headers, ids, vendor, bill_price="10500"
        )
        r = await client.post(
            f"/api/v1/proc/bills/{flow['bill']['ap_bill_id']}/match",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "DISPUTED"
        assert "Selisih harga" in body["reason"]

        # No GL posted for the disputed bill.
        conn = await asyncpg.connect(DB)
        try:
            count = await conn.fetchval(
                "SELECT count(*) FROM journal_entries "
                "WHERE description LIKE 'AP Bill Matched%'"
            )
            assert count == 0
            reason = await conn.fetchval(
                "SELECT dispute_reason FROM ap_bills"
            )
            assert reason is not None and "Selisih harga" in reason
        finally:
            await conn.close()


@pytest.mark.asyncio
async def test_receipt_exceeds_and_inspect_twice():
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

        po = await _mk_po(client, headers, ids, vendor, "PO-001")
        r = await client.post(
            f"/api/v1/proc/orders/{po['id']}/submit", headers=headers
        )
        assert r.status_code == 200, r.text
        r = await client.post(
            f"/api/v1/proc/orders/{po['id']}/approve", headers=headers
        )
        assert r.status_code == 200, r.text

        # Over-receipt: 11 > 10 ordered -> RECEIPT_EXCEEDS_ORDER.
        r = await client.post(
            f"/api/v1/proc/orders/{po['id']}/receive",
            headers=headers,
            json={
                "received_date": "2026-09-02",
                "lines": [
                    {
                        "purchase_order_line_id": po["lines"][0]["id"],
                        "qty_received": "11",
                    }
                ],
            },
        )
        assert r.status_code == 422, r.text
        assert "RECEIPT_EXCEEDS_ORDER" in r.text

        # Correct receipt then inspect twice.
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

        payload = {
            "line_results": [
                {
                    "grn_line_id": grn_line_id,
                    "qty_accepted": "10",
                    "qty_rejected": "0",
                }
            ]
        }
        r = await client.post(
            f"/api/v1/proc/grns/{grn['grn_id']}/inspect",
            headers=headers, json=payload,
        )
        assert r.status_code == 200, r.text

        r = await client.post(
            f"/api/v1/proc/grns/{grn['grn_id']}/inspect",
            headers=headers, json=payload,
        )
        assert r.status_code == 422, r.text
        assert "GRN_ALREADY_INSPECTED" in r.text


@pytest.mark.asyncio
async def test_bill_guards():
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

        # PO not approved yet -> receive must fail.
        po = await _mk_po(client, headers, ids, vendor, "PO-001")
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
        assert r.status_code == 422, r.text
        assert "PO_INVALID_STATUS" in r.text

        # Double submit rejected.
        r = await client.post(
            f"/api/v1/proc/orders/{po['id']}/submit", headers=headers
        )
        assert r.status_code == 200, r.text
        r = await client.post(
            f"/api/v1/proc/orders/{po['id']}/submit", headers=headers
        )
        assert r.status_code == 422, r.text
        assert "PO_INVALID_STATUS" in r.text

        # Bill from un-inspected GRN -> GRN_NOT_INSPECTED.
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
            "/api/v1/proc/bills",
            headers=headers,
            json={
                "grn_id": grn["grn_id"],
                "bill_number": "BILL-001",
                "bill_date": "2026-09-03",
                "lines": [
                    {
                        "item_id": ids["_item"],
                        "qty": "10",
                        "unit_price": "10000",
                    }
                ],
            },
        )
        assert r.status_code == 422, r.text
        assert "GRN_NOT_INSPECTED" in r.text

        # Inspect then double-bill -> GRN_ALREADY_BILLED.
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
                        "qty_accepted": "10",
                        "qty_rejected": "0",
                    }
                ]
            },
        )
        assert r.status_code == 200, r.text

        bill_json = {
            "grn_id": grn["grn_id"],
            "bill_number": "BILL-001",
            "bill_date": "2026-09-03",
            "lines": [
                {
                    "item_id": ids["_item"],
                    "qty": "10",
                    "unit_price": "10000",
                }
            ],
        }
        r = await client.post(
            "/api/v1/proc/bills", headers=headers, json=bill_json
        )
        assert r.status_code == 201, r.text

        bill_json["bill_number"] = "BILL-002"
        r = await client.post(
            "/api/v1/proc/bills", headers=headers, json=bill_json
        )
        assert r.status_code == 422, r.text
        assert "GRN_ALREADY_BILLED" in r.text
