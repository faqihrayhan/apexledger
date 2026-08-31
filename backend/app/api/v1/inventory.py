"""
Inventory API routes (Module 3).

RPC wrappers for stock movements + typed CRUD for master data
(warehouses, items, work orders). Business rules live in the
PL/pgSQL RPCs; this layer validates, scopes, and maps errors.

Role model (PRD 3.6):
- receive/transfer: WAREHOUSE_OPERATOR, DEPT_HEAD_WAREHOUSE, SUPER_ADMIN
- issue (manual): warehouse + finance roles
- complete WO: DEPT_HEAD_WAREHOUSE, FINANCE_OPERATOR, SUPER_ADMIN
"""

from __future__ import annotations

import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_with_rls
from app.core.rpc_errors import raise_from_rpc
from app.core.security import get_current_user
from app.models.inventory import Item, Warehouse, WorkOrder
from app.schemas.inventory import (
    CompleteWorkOrderRequest,
    CompleteWorkOrderResponse,
    IssueStockRequest,
    IssueStockResponse,
    ItemCreate,
    ItemResponse,
    ReceiveStockRequest,
    ReceiveStockResponse,
    TransferStockRequest,
    TransferStockResponse,
    WarehouseCreate,
    WarehouseResponse,
    WorkOrderCreate,
    WorkOrderResponse,
)

router = APIRouter(prefix="/inv", tags=["Inventory"])

WAREHOUSE_ROLES = {"WAREHOUSE_OPERATOR", "DEPT_HEAD_WAREHOUSE", "SUPER_ADMIN"}
WO_ROLES = {"DEPT_HEAD_WAREHOUSE", "FINANCE_OPERATOR", "SUPER_ADMIN"}


def _parse_rpc_json(raw: object) -> dict:
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)  # type: ignore[arg-type]


def _require_roles(current_user: dict, roles: set[str]) -> None:
    if current_user["role"] not in roles:
        raise HTTPException(
            status_code=403, detail="Insufficient role for this operation."
        )


# ---------------------------------------------------------------------------
# Warehouses
# ---------------------------------------------------------------------------


@router.get("/warehouses", response_model=list[WarehouseResponse])
async def list_warehouses(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[WarehouseResponse]:
    stmt = (
        select(Warehouse)
        .where(Warehouse.entity_id == current_user["entity_id"])
        .order_by(Warehouse.code)
    )
    result = await db.execute(stmt)
    return [
        WarehouseResponse(
            id=w.id, code=w.code, name=w.name,
            warehouse_type=w.warehouse_type, is_active=w.is_active,
        )
        for w in result.scalars().all()
    ]


@router.post("/warehouses", response_model=WarehouseResponse, status_code=201)
async def create_warehouse(
    payload: WarehouseCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> WarehouseResponse:
    _require_roles(current_user, WAREHOUSE_ROLES)

    warehouse = Warehouse(
        entity_id=current_user["entity_id"],
        code=payload.code,
        name=payload.name,
        warehouse_type=payload.warehouse_type,
    )
    db.add(warehouse)
    try:
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        if "unique" in str(exc.orig).lower():  # type: ignore[union-attr]
            raise HTTPException(
                status_code=409,
                detail=f"Warehouse code {payload.code} already exists.",
            ) from exc
        raise
    await db.refresh(warehouse)
    return WarehouseResponse(
        id=warehouse.id, code=warehouse.code, name=warehouse.name,
        warehouse_type=warehouse.warehouse_type,
        is_active=warehouse.is_active,
    )


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


@router.get("/items", response_model=list[ItemResponse])
async def list_items(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
    active_only: bool = Query(default=True),
) -> list[ItemResponse]:
    stmt = select(Item).where(Item.entity_id == current_user["entity_id"])
    if active_only:
        stmt = stmt.where(Item.is_active.is_(True))
    stmt = stmt.order_by(Item.item_code)
    result = await db.execute(stmt)
    return [
        ItemResponse(
            id=i.id, item_code=i.item_code, item_name=i.item_name,
            item_type=i.item_type, costing_method=i.costing_method,
            uom_base=i.uom_base, requires_fefo=i.requires_fefo,
            is_active=i.is_active,
            gl_inventory_account_id=i.gl_inventory_account_id,
            gl_cogs_account_id=i.gl_cogs_account_id,
        )
        for i in result.scalars().all()
    ]


@router.post("/items", response_model=ItemResponse, status_code=201)
async def create_item(
    payload: ItemCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> ItemResponse:
    _require_roles(current_user, WAREHOUSE_ROLES)

    item = Item(
        entity_id=current_user["entity_id"],
        item_code=payload.item_code,
        item_name=payload.item_name,
        item_type=payload.item_type,
        costing_method=payload.costing_method,
        uom_base=payload.uom_base,
        requires_fefo=payload.requires_fefo,
        gl_inventory_account_id=payload.gl_inventory_account_id,
        gl_cogs_account_id=payload.gl_cogs_account_id,
    )
    db.add(item)
    try:
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        if "unique" in str(exc.orig).lower():  # type: ignore[union-attr]
            raise HTTPException(
                status_code=409,
                detail=f"Item code {payload.item_code} already exists.",
            ) from exc
        raise
    await db.refresh(item)
    return ItemResponse(
        id=item.id, item_code=item.item_code, item_name=item.item_name,
        item_type=item.item_type, costing_method=item.costing_method,
        uom_base=item.uom_base, requires_fefo=item.requires_fefo,
        is_active=item.is_active,
        gl_inventory_account_id=item.gl_inventory_account_id,
        gl_cogs_account_id=item.gl_cogs_account_id,
    )


# ---------------------------------------------------------------------------
# Stock movements (RPC wrappers)
# ---------------------------------------------------------------------------


@router.post("/stock/receive", response_model=ReceiveStockResponse)
async def receive_stock(
    payload: ReceiveStockRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> ReceiveStockResponse:
    """Receive stock (GRN / WO output / adjustment-in)."""
    _require_roles(current_user, WAREHOUSE_ROLES | {"FINANCE_OPERATOR"})

    # asyncpg requires a real date object when the target type is DATE
    # (CAST infers the type); strings raise DataError.
    from datetime import date as date_cls

    expiry_obj = None
    if payload.expiry_date is not None:
        if isinstance(payload.expiry_date, str):
            expiry_obj = date_cls.fromisoformat(payload.expiry_date)
        else:
            expiry_obj = payload.expiry_date

    try:
        result = await db.execute(
            text(
                "SELECT fn_receive_stock("
                "  CAST(:item_id AS uuid), CAST(:wh_id AS uuid),"
                "  CAST(:qty AS numeric), CAST(:unit_cost AS numeric),"
                "  :ref_type, CAST(:ref_id AS uuid),"
                "  CAST(:expiry AS date)"
                ") AS rpc"
            ),
            {
                "item_id": str(payload.item_id),
                "wh_id": str(payload.warehouse_id),
                "qty": str(payload.qty),
                "unit_cost": str(payload.unit_cost),
                "ref_type": payload.reference_type,
                "ref_id": (
                    str(payload.reference_id) if payload.reference_id else None
                ),
                "expiry": expiry_obj,
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return ReceiveStockResponse(
            transaction_id=rpc["transaction_id"],
            qty=str(rpc["qty"]),
            unit_cost=str(rpc["unit_cost"]),
        )

    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.post("/stock/issue", response_model=IssueStockResponse)
async def issue_stock(
    payload: IssueStockRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> IssueStockResponse:
    """Issue stock (manual or module-driven)."""
    _require_roles(current_user, WAREHOUSE_ROLES | {"FINANCE_OPERATOR"})

    try:
        result = await db.execute(
            text(
                "SELECT fn_issue_stock("
                "  CAST(:item_id AS uuid), CAST(:wh_id AS uuid),"
                "  CAST(:qty AS numeric), :ref_type, CAST(:ref_id AS uuid)"
                ") AS rpc"
            ),
            {
                "item_id": str(payload.item_id),
                "wh_id": str(payload.warehouse_id),
                "qty": str(payload.qty),
                "ref_type": payload.reference_type,
                "ref_id": (
                    str(payload.reference_id) if payload.reference_id else None
                ),
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return IssueStockResponse(
            transaction_id=rpc["transaction_id"],
            qty=str(rpc["qty"]),
            total_cost=str(rpc["total_cost"]),
            weighted_unit_cost=str(rpc["weighted_unit_cost"]),
        )

    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.post("/stock/transfer", response_model=TransferStockResponse)
async def transfer_stock(
    payload: TransferStockRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> TransferStockResponse:
    """Transfer stock between warehouses of the same entity (atomic)."""
    _require_roles(current_user, WAREHOUSE_ROLES)

    try:
        result = await db.execute(
            text(
                "SELECT fn_transfer_stock("
                "  CAST(:item_id AS uuid), CAST(:from_wh AS uuid),"
                "  CAST(:to_wh AS uuid), CAST(:qty AS numeric)"
                ") AS rpc"
            ),
            {
                "item_id": str(payload.item_id),
                "from_wh": str(payload.from_warehouse_id),
                "to_wh": str(payload.to_warehouse_id),
                "qty": str(payload.qty),
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return TransferStockResponse(
            qty_transferred=str(rpc["qty_transferred"]),
            unit_cost=str(rpc["unit_cost"]),
        )

    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


# ---------------------------------------------------------------------------
# Work orders
# ---------------------------------------------------------------------------


@router.get("/work-orders", response_model=list[WorkOrderResponse])
async def list_work_orders(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[WorkOrderResponse]:
    stmt = (
        select(WorkOrder)
        .where(WorkOrder.entity_id == current_user["entity_id"])
        .order_by(WorkOrder.created_at.desc())
        .limit(100)
    )
    result = await db.execute(stmt)
    return [
        WorkOrderResponse(
            id=w.id, wo_number=w.wo_number, bom_id=w.bom_id,
            item_id=w.item_id, warehouse_id=w.warehouse_id,
            cost_center_id=w.cost_center_id,
            qty_planned=str(w.qty_planned),
            qty_produced=str(w.qty_produced) if w.qty_produced else None,
            status=w.status, journal_entry_id=w.journal_entry_id,
        )
        for w in result.scalars().all()
    ]


@router.post("/work-orders", response_model=WorkOrderResponse, status_code=201)
async def create_work_order(
    payload: WorkOrderCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> WorkOrderResponse:
    _require_roles(current_user, WO_ROLES)

    wo = WorkOrder(
        entity_id=current_user["entity_id"],
        wo_number=payload.wo_number,
        bom_id=payload.bom_id,
        item_id=payload.item_id,
        warehouse_id=payload.warehouse_id,
        cost_center_id=payload.cost_center_id,
        qty_planned=Decimal(payload.qty_planned),
        direct_labor_cost=Decimal(payload.direct_labor_cost),
        gl_accrued_labor_account_id=payload.gl_accrued_labor_account_id,
        driver_qty_used=Decimal(payload.driver_qty_used),
        created_by=current_user["user_id"],
        status="DRAFT",
    )
    db.add(wo)
    try:
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        if "unique" in str(exc.orig).lower():  # type: ignore[union-attr]
            raise HTTPException(
                status_code=409,
                detail=f"Work order {payload.wo_number} already exists.",
            ) from exc
        raise
    await db.refresh(wo)
    return WorkOrderResponse(
        id=wo.id, wo_number=wo.wo_number, bom_id=wo.bom_id,
        item_id=wo.item_id, warehouse_id=wo.warehouse_id,
        cost_center_id=wo.cost_center_id,
        qty_planned=str(wo.qty_planned),
        qty_produced=str(wo.qty_produced) if wo.qty_produced else None,
        status=wo.status, journal_entry_id=wo.journal_entry_id,
    )


@router.post(
    "/work-orders/{wo_id}/complete",
    response_model=CompleteWorkOrderResponse,
)
async def complete_work_order(
    wo_id: str,
    payload: CompleteWorkOrderRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> CompleteWorkOrderResponse:
    """Complete a work order: consume BOM, compute COGM, post GL."""
    _require_roles(current_user, WO_ROLES)

    try:
        result = await db.execute(
            text(
                "SELECT fn_complete_work_order("
                "  CAST(:wo_id AS uuid), CAST(:qty AS numeric)"
                ") AS rpc"
            ),
            {"wo_id": wo_id, "qty": str(payload.qty_produced)},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return CompleteWorkOrderResponse(
            work_order_id=rpc["work_order_id"],
            cogm=str(rpc["cogm"]),
            unit_cost=str(rpc["unit_cost"]),
            material_cost=str(rpc["material_cost"]),
            foh_allocated=str(rpc["foh_allocated"]),
        )

    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


# ---------------------------------------------------------------------------
# Stock on hand (read)
# ---------------------------------------------------------------------------


@router.get("/stock/on-hand")
async def stock_on_hand(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
    warehouse_id: str | None = Query(default=None),
) -> list[dict]:
    """Current stock levels per item/warehouse for the caller's entity."""
    sql = text(
        "SELECT i.item_code, i.item_name, w.code AS warehouse_code, "
        "       s.qty_on_hand, s.avg_cost "
        "FROM item_warehouse_stock s "
        "JOIN items i ON i.id = s.item_id "
        "JOIN warehouses w ON w.id = s.warehouse_id "
        "WHERE i.entity_id = CAST(:entity_id AS uuid) "
        "  AND (CAST(:wh_id AS uuid) IS NULL OR s.warehouse_id = CAST(:wh_id AS uuid)) "
        "ORDER BY i.item_code, w.code"
    )
    rows = await db.execute(
        sql,
        {
            "entity_id": str(current_user["entity_id"]),
            "wh_id": warehouse_id,
        },
    )
    return [
        {
            "item_code": r.item_code,
            "item_name": r.item_name,
            "warehouse_code": r.warehouse_code,
            "qty_on_hand": str(r.qty_on_hand),
            "avg_cost": str(r.avg_cost),
        }
        for r in rows
    ]
