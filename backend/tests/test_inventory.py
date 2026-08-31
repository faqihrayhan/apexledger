"""
Module 3 — Inventory & Costing integration tests.

Hand-computed scenarios:

S1 Moving Average (SKU-MA, GUDANG-A):
  receive 100 @ 10  -> avg 10.00
  receive 100 @ 20  -> avg (100*10 + 100*20)/200 = 15.00
  issue 50         -> cost 50 x 15.00 = 750.00, avg stays 15.00
  issue 60 (over remaining 150 ok) -> 60 x 15 = 900
  issue 100 (over 90 left)  -> INSUFFICIENT_STOCK

S2 FIFO layer burn (SKU-FIFO, GUDANG-A):
  receive lot1 100 @ 10 (2026-01-01)
  receive lot2 100 @ 30 (2026-01-02)
  issue 150 -> 100@10 + 50@30 = 1000 + 1500 = 2500.00
  remaining 50 all @ 30 -> issue 50 = 1500.00; issue 1 more -> INSUFFICIENT

S3 FEFO expiry (SKU-FEFO, GUDANG-A, requires_fefo):
  receive 10 @ 5 expiry 2027-01-01 (far)
  receive 10 @ 8 expiry 2026-09-01 (near)  <- consumed FIRST despite newer
  issue 10 -> must burn the 2026-09-01 lot: cost 80.00 (not 50.00)
  receive 10 @ 5 without expiry -> EXPIRY_DATE_REQUIRED

S4 Work order COGM (FG SKU-PIE from BOM: 2 raws + labor + FOH):
  BOM: 1 flour (avg 2,000/kg) + 1 sugar (avg 3,000/kg) per 1 pie,
       waste 10% on flour -> flour needed = 1 * (10/10) * 1.1 = 1.1 kg
  Materials: 1.1*2000 + 1*3000 = 2200 + 3000 = 5,200.00
  Labor 1,500.00; FOH: rate = 2,000,000/400 = 5,000/hr x 0.3 hr = 1,500.00
  COGM = 5,200 + 1,500 + 1,500 = 8,200.00 for 10 pies
  unit_cost = 820.00/pie (rounded 4dp)
  GL: Dr FG Inventory 8,200 | Cr RawMat-A 2,200 Cr RawMat-B 3,000
      Cr Accrued Labor 1,500 Cr FOH Applied 1,500 -> balanced

S5 Transfer (SKU-MA GUDANG-A -> GUDANG-B):
  issue from A at avg 15 + receive B at weighted cost — atomic.
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


async def _seed_coa() -> dict[str, str]:
    """Create the GL accounts used by inventory items."""
    accounts = {
        "1101": ("Raw Material A", "ASSET"),
        "1102": ("Raw Material B", "ASSET"),
        "1103": ("Finished Goods", "ASSET"),
        "5201": ("FOH Applied", "EXPENSE"),
        "5301": ("Direct Labor Accrued", "LIABILITY"),
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
    finally:
        await conn.close()
    return created


async def _mk_warehouse(client, headers, code: str) -> str:
    resp = await client.post(
        "/api/v1/inv/warehouses",
        headers=headers,
        json={"code": code, "name": f"Gudang {code}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _mk_item(client, headers, code: str, **kw) -> str:
    payload = {
        "item_code": code,
        "item_name": code,
        "item_type": "RAW_MATERIAL",
        "costing_method": "MOVING_AVERAGE",
        "uom_base": "KG",
        "requires_fefo": False,
    }
    payload.update(kw)
    resp = await client.post("/api/v1/inv/items", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _receive(client, headers, item, wh, qty, cost, **kw) -> dict:
    payload = {
        "item_id": item, "warehouse_id": wh,
        "qty": qty, "unit_cost": cost, "reference_type": "GRN",
    }
    payload.update(kw)
    resp = await client.post(
        "/api/v1/inv/stock/receive", headers=headers, json=payload
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _issue(client, headers, item, wh, qty) -> dict:
    resp = await client.post(
        "/api/v1/inv/stock/issue",
        headers=headers,
        json={"item_id": item, "warehouse_id": wh, "qty": qty,
              "reference_type": "MANUAL"},
    )
    return resp


@pytest.mark.asyncio
async def test_moving_average_and_anti_negative():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        coa = await _seed_coa()
        wh = await _mk_warehouse(client, headers, "GA")
        item = await _mk_item(client, headers, "SKU-MA",
                              gl_inventory_account_id=coa["1101"])

        await _receive(client, headers, item, wh, "100", "10")
        await _receive(client, headers, item, wh, "100", "20")

        r = await _issue(client, headers, item, wh, "50")
        assert r.status_code == 200, r.text
        assert _amt(r.json()["total_cost"]) == _amt("750.00")
        assert _amt(r.json()["weighted_unit_cost"]) == _amt("15.0000")

        r = await _issue(client, headers, item, wh, "60")
        assert r.status_code == 200, r.text
        assert _amt(r.json()["total_cost"]) == _amt("900.00")

        # 150 - 110 = 40 left; asking 100 -> INSUFFICIENT_STOCK
        r = await _issue(client, headers, item, wh, "100")
        assert r.status_code == 422, r.text
        assert "INSUFFICIENT_STOCK" in r.text


@pytest.mark.asyncio
async def test_fifo_layer_burn():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        coa = await _seed_coa()
        wh = await _mk_warehouse(client, headers, "GA")
        item = await _mk_item(client, headers, "SKU-FIFO",
                              costing_method="FIFO",
                              gl_inventory_account_id=coa["1101"])

        await _receive(client, headers, item, wh, "100", "10")
        await _receive(client, headers, item, wh, "100", "30")

        r = await _issue(client, headers, item, wh, "150")
        assert r.status_code == 200, r.text
        # 100 @ 10 + 50 @ 30 = 2500
        assert _amt(r.json()["total_cost"]) == _amt("2500.00")

        r = await _issue(client, headers, item, wh, "50")
        assert r.status_code == 200, r.text
        assert _amt(r.json()["total_cost"]) == _amt("1500.00")

        r = await _issue(client, headers, item, wh, "1")
        assert r.status_code == 422
        assert "INSUFFICIENT_STOCK" in r.text


@pytest.mark.asyncio
async def test_fefo_expiry():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        coa = await _seed_coa()
        wh = await _mk_warehouse(client, headers, "GA")
        item = await _mk_item(client, headers, "SKU-FEFO",
                              costing_method="FIFO", requires_fefo=True,
                              gl_inventory_account_id=coa["1101"])

        # FEFO receive without expiry -> rejected.
        r = await client.post(
            "/api/v1/inv/stock/receive",
            headers=headers,
            json={"item_id": item, "warehouse_id": wh,
                  "qty": "10", "unit_cost": "5", "reference_type": "GRN"},
        )
        assert r.status_code == 422, r.text
        assert "EXPIRY_DATE_REQUIRED" in r.text

        await _receive(client, headers, item, wh, "10", "5",
                       expiry_date="2027-01-01")
        await _receive(client, headers, item, wh, "10", "8",
                       expiry_date="2026-09-01")

        # FEFO: nearest expiry first -> burns the @8 lot.
        r = await _issue(client, headers, item, wh, "10")
        assert r.status_code == 200, r.text
        assert _amt(r.json()["total_cost"]) == _amt("80.00")


@pytest.mark.asyncio
async def test_work_order_cogm():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        coa = await _seed_coa()
        wh = await _mk_warehouse(client, headers, "GA")

        flour = await _mk_item(client, headers, "SKU-FLOUR",
                               gl_inventory_account_id=coa["1101"])
        sugar = await _mk_item(client, headers, "SKU-SUGAR",
                               gl_inventory_account_id=coa["1102"])
        pie = await _mk_item(client, headers, "SKU-PIE",
                              item_type="FINISHED_GOOD",
                              gl_inventory_account_id=coa["1103"])

        await _receive(client, headers, flour, wh, "100", "2000")
        await _receive(client, headers, sugar, wh, "100", "3000")

        # BOM: 1 flour + 1 sugar per 1 pie, flour waste 10%.
        conn = await asyncpg.connect(TEST_DSN)
        try:
            entity_id = await conn.fetchval("SELECT id FROM entities LIMIT 1")
            bom_id = await conn.fetchval(
                "INSERT INTO boms (entity_id, item_id, bom_type, yield_qty) "
                "VALUES ($1, $2, 'RECIPE', 10) RETURNING id",
                entity_id, uuid.UUID(pie),
            )
            await conn.execute(
                "INSERT INTO bom_components (bom_id, component_item_id, "
                "qty_per_yield, waste_pct, sequence_no) VALUES "
                "($1, $2, 1, 10, 1), ($1, $3, 1, 0, 2)",
                bom_id, uuid.UUID(flour), uuid.UUID(sugar),
            )
            cc_id = await conn.fetchval(
                "INSERT INTO cost_centers (entity_id, code, name, "
                "total_estimated_overhead, total_capacity_driver, "
                "driver_unit, gl_foh_applied_account_id) "
                "VALUES ($1, 'CC1', 'Kitchen', 2000000, 400, "
                "'LABOR_HOURS', $2) RETURNING id",
                entity_id, uuid.UUID(coa["5201"]),
            )
        finally:
            await conn.close()

        # WO: 10 pies planned, labor 1500, driver 0.3 hr.
        resp = await client.post(
            "/api/v1/inv/work-orders",
            headers=headers,
            json={
                "bom_id": str(bom_id), "item_id": pie,
                "warehouse_id": wh, "wo_number": "WO-0001",
                "qty_planned": "10",
                "cost_center_id": str(cc_id),
                "direct_labor_cost": "1500",
                "gl_accrued_labor_account_id": coa["5301"],
                "driver_qty_used": "0.3",
            },
        )
        assert resp.status_code == 201, resp.text
        wo_id = resp.json()["id"]

        resp = await client.post(
            f"/api/v1/inv/work-orders/{wo_id}/complete",
            headers=headers,
            json={"qty_produced": "10"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Materials: 1.1*2000 + 1*3000 = 5200
        assert _amt(body["material_cost"]) == _amt("5200.00")
        assert _amt(body["foh_allocated"]) == _amt("1500.00")
        assert _amt(body["cogm"]) == _amt("8200.00")
        assert _amt(body["unit_cost"]) == _amt("820.0000")

        # GL journal balanced: Dr FG 8200 = Cr (2200+3000+1500+1500).
        conn = await asyncpg.connect(TEST_DSN)
        try:
            rows = await conn.fetch(
                "SELECT je.id, SUM(jl.debit_amount) dr, SUM(jl.credit_amount) cr "
                "FROM journal_entries je JOIN journal_lines jl "
                "  ON jl.journal_entry_id = je.id "
                "WHERE je.description LIKE 'WO Completion WO-0001%' "
                "GROUP BY je.id"
            )
            assert len(rows) == 1
            assert _amt(str(rows[0]["dr"])) == _amt("8200.00")
            assert _amt(str(rows[0]["cr"])) == _amt("8200.00")

            # Work order completed & FG received.
            wo = await conn.fetchrow(
                "SELECT status, qty_produced FROM work_orders "
                "WHERE wo_number = 'WO-0001'"
            )
            assert wo["status"] == "COMPLETED"
            assert _amt(str(wo["qty_produced"])) == _amt("10")

            fg_stock = await conn.fetchval(
                "SELECT qty_on_hand FROM item_warehouse_stock s "
                "JOIN items i ON i.id = s.item_id "
                "WHERE i.item_code = 'SKU-PIE'"
            )
            assert _amt(str(fg_stock)) == _amt("10")
        finally:
            await conn.close()


@pytest.mark.asyncio
async def test_transfer_stock():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _bootstrap(client)
        headers = {"Authorization": f"Bearer {token}"}
        coa = await _seed_coa()
        wh_a = await _mk_warehouse(client, headers, "GA")
        wh_b = await _mk_warehouse(client, headers, "GB")
        item = await _mk_item(client, headers, "SKU-MA",
                              gl_inventory_account_id=coa["1101"])

        await _receive(client, headers, item, wh_a, "100", "10")
        await _receive(client, headers, item, wh_a, "100", "20")

        resp = await client.post(
            "/api/v1/inv/stock/transfer",
            headers=headers,
            json={"item_id": item, "from_warehouse_id": wh_a,
                  "to_warehouse_id": wh_b, "qty": "50"},
        )
        assert resp.status_code == 200, resp.text
        assert _amt(resp.json()["unit_cost"]) == _amt("15.0000")

        # Stock on hand per warehouse reflects the transfer.
        resp = await client.get(
            f"/api/v1/inv/stock/on-hand?warehouse_id={wh_b}",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert len(rows) == 1
        assert _amt(rows[0]["qty_on_hand"]) == _amt("50")
        assert _amt(rows[0]["avg_cost"]) == _amt("15.0000")
