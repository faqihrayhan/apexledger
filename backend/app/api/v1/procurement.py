"""
Procurement & AP API routes (Module 5).

RPC wrappers for the PUTG flow (PO submit/approve -> GRN ->
inspection -> AP bill -> 3-way match -> payment) + typed reads.
Business rules live in the PL/pgSQL RPCs; this layer enforces
authentication, coarse role guards, and entity scoping via RLS.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_with_rls
from app.api.v1.sales import _parse_rpc_json, _require_roles
from app.core.rpc_errors import raise_from_rpc
from app.core.security import get_current_user
from app.models.procurement import (
    ApBill,
    GoodsReceivedNote,
    GrnLine,
    LandedCost,
    LandedCostAllocMethodEnum,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseReturn,
    PurchaseReturnLine,
    Vendor,
)
from app.schemas.procurement import (
    AllocateLandedCostResponse,
    ApPaymentRequest,
    ApPaymentResponse,
    ApprovePoResponse,
    ApprovePurchaseReturnResponse,
    CreateApBillRequest,
    CreateApBillResponse,
    InspectGrnRequest,
    InspectGrnResponse,
    LandedCostCreate,
    LandedCostResponse,
    MatchApBillResponse,
    PoCreate,
    PoLineOut,
    PoResponse,
    PurchaseReturnCreate,
    PurchaseReturnResponse,
    ReceiveGoodsRequest,
    ReceiveGoodsResponse,
    SubmitPoResponse,
    VendorCreate,
    VendorResponse,
)

router = APIRouter(prefix="/proc", tags=["procurement"])

# Role sets (coarse, second layer after RPC guards).
PROCUREMENT_ROLES = {
    "WAREHOUSE_OPERATOR",
    "DEPT_HEAD_WAREHOUSE",
    "FINANCE_OPERATOR",
    "SUPER_ADMIN",
}
FINANCE_ROLES = {"FINANCE_OPERATOR", "DEPT_HEAD_FA", "SUPER_ADMIN"}


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------


@router.post(
    "/vendors", response_model=VendorResponse, status_code=201
)
async def create_vendor(
    payload: VendorCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> VendorResponse:
    _require_roles(current_user, PROCUREMENT_ROLES)
    vendor = Vendor(
        entity_id=current_user["entity_id"],
        vendor_code=payload.vendor_code,
        vendor_name=payload.vendor_name,
        payment_term_days=payload.payment_term_days,
        npwp=payload.npwp,
    )
    db.add(vendor)
    try:
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        if "unique" in str(exc.orig).lower():  # type: ignore[union-attr]
            raise HTTPException(
                status_code=409,
                detail=f"Vendor code {payload.vendor_code} "
                "already exists.",
            ) from exc
        raise
    await db.refresh(vendor)
    return VendorResponse.model_validate(vendor)


@router.get("/vendors", response_model=list[VendorResponse])
async def list_vendors(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[VendorResponse]:
    stmt = (
        select(Vendor)
        .where(Vendor.entity_id == current_user["entity_id"])
        .order_by(Vendor.vendor_code)
        .limit(200)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [VendorResponse.model_validate(v) for v in rows]


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------


@router.post("/orders", response_model=PoResponse, status_code=201)
async def create_purchase_order(
    payload: PoCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> PoResponse:
    _require_roles(current_user, PROCUREMENT_ROLES)
    po = PurchaseOrder(
        entity_id=current_user["entity_id"],
        vendor_id=payload.vendor_id,
        warehouse_id=payload.warehouse_id,
        po_number=payload.po_number,
        order_date=payload.order_date,
        created_by=current_user["user_id"],
    )
    db.add(po)
    try:
        await db.flush()
        for line in payload.lines:
            qty = Decimal(line.qty_ordered)
            price = Decimal(line.unit_price)
            db.add(
                PurchaseOrderLine(
                    purchase_order_id=po.id,
                    item_id=line.item_id,
                    qty_ordered=qty,
                    unit_price=price,
                    line_total=round(qty * price, 2),
                )
            )
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        if "unique" in str(exc.orig).lower():  # type: ignore[union-attr]
            raise HTTPException(
                status_code=409,
                detail=f"PO number {payload.po_number} "
                "already exists.",
            ) from exc
        raise
    await db.refresh(po)
    lines = (
        await db.execute(
            select(PurchaseOrderLine).where(
                PurchaseOrderLine.purchase_order_id == po.id
            )
        )
    ).scalars().all()
    return PoResponse(
        id=po.id,
        po_number=po.po_number,
        status=str(po.status),
        total_amount=str(po.total_amount),
        required_approval_role=po.required_approval_role,
        lines=[
            PoLineOut(
                id=ln.id,
                item_id=ln.item_id,
                qty_ordered=str(ln.qty_ordered),
                qty_received=str(ln.qty_received),
                unit_price=str(ln.unit_price),
                line_total=str(ln.line_total),
            )
            for ln in lines
        ],
    )


@router.get("/orders", response_model=list[PoResponse])
async def list_purchase_orders(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[PoResponse]:
    stmt = (
        select(PurchaseOrder)
        .where(PurchaseOrder.entity_id == current_user["entity_id"])
        .order_by(PurchaseOrder.order_date.desc())
        .limit(100)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        PoResponse(
            id=po.id,
            po_number=po.po_number,
            status=str(po.status),
            total_amount=str(po.total_amount),
            required_approval_role=po.required_approval_role,
            lines=[],
        )
        for po in rows
    ]


@router.post("/orders/{po_id}/submit", response_model=SubmitPoResponse)
async def submit_purchase_order(
    po_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> SubmitPoResponse:
    _require_roles(current_user, PROCUREMENT_ROLES)
    try:
        result = await db.execute(
            text(
                "SELECT fn_submit_purchase_order("
                "  CAST(:po_id AS uuid)"
                ") AS rpc"
            ),
            {"po_id": po_id},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return SubmitPoResponse(
            purchase_order_id=rpc["purchase_order_id"],
            required_approval_role=rpc["required_approval_role"],
            total_amount=str(rpc["total_amount"]),
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.post("/orders/{po_id}/approve", response_model=ApprovePoResponse)
async def approve_purchase_order(
    po_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> ApprovePoResponse:
    try:
        result = await db.execute(
            text(
                "SELECT fn_approve_purchase_order("
                "  CAST(:po_id AS uuid)"
                ") AS rpc"
            ),
            {"po_id": po_id},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return ApprovePoResponse(
            purchase_order_id=rpc["purchase_order_id"],
            status=rpc["status"],
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


# ---------------------------------------------------------------------------
# GRN: receive goods + inspect (PUTG)
# ---------------------------------------------------------------------------


@router.post(
    "/orders/{po_id}/receive", response_model=ReceiveGoodsResponse
)
async def receive_goods(
    po_id: str,
    payload: ReceiveGoodsRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> ReceiveGoodsResponse:
    _require_roles(
        current_user, {"WAREHOUSE_OPERATOR", "DEPT_HEAD_WAREHOUSE",
                        "SUPER_ADMIN"},
    )
    lines_json = json.dumps(
        [
            {
                "purchase_order_line_id": str(ln.purchase_order_line_id),
                "qty_received": ln.qty_received,
            }
            for ln in payload.lines
        ]
    )
    try:
        result = await db.execute(
            text(
                "SELECT fn_receive_goods("
                "  CAST(:po_id AS uuid),"
                "  CAST(:received_date AS date),"
                "  CAST(:lines AS jsonb)"
                ") AS rpc"
            ),
            {
                "po_id": po_id,
                "received_date": payload.received_date,
                "lines": lines_json,
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return ReceiveGoodsResponse(
            grn_id=rpc["grn_id"],
            grn_number=rpc["grn_number"],
            inspection_status=rpc["inspection_status"],
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.get("/grns/{grn_id}", response_model=ReceiveGoodsResponse)
async def get_grn(
    grn_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> ReceiveGoodsResponse:
    stmt = select(GoodsReceivedNote).where(
        GoodsReceivedNote.entity_id == current_user["entity_id"],
        GoodsReceivedNote.id == uuid.UUID(grn_id),
    )
    grn = (await db.execute(stmt)).scalar_one_or_none()
    if grn is None:
        raise HTTPException(status_code=404, detail="GRN not found.")
    return ReceiveGoodsResponse(
        grn_id=grn.id,
        grn_number=grn.grn_number,
        inspection_status=str(grn.inspection_status),
    )


@router.get("/grns", response_model=list[dict])
async def list_grns(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List GRNs for the current entity (newest first, capped)."""
    stmt = (
        select(GoodsReceivedNote)
        .where(GoodsReceivedNote.entity_id == current_user["entity_id"])
        .order_by(GoodsReceivedNote.received_date.desc())
        .limit(100)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "grn_id": str(g.id),
            "grn_number": g.grn_number,
            "purchase_order_id": str(g.purchase_order_id),
            "warehouse_id": str(g.warehouse_id),
            "received_date": g.received_date.isoformat(),
            "status": str(g.status),
            "inspection_status": str(g.inspection_status),
        }
        for g in rows
    ]


@router.get("/grns/{grn_id}/lines", response_model=list[dict])
async def list_grn_lines(
    grn_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """GRN line detail — exposes grn_line_id needed by inspect/return flows.

    Entity scoping happens through the parent GRN (RLS on the GRN
    table); grn_lines inherit the same scope via the FK chain.
    """
    stmt = select(GoodsReceivedNote.id).where(
        GoodsReceivedNote.entity_id == current_user["entity_id"],
        GoodsReceivedNote.id == uuid.UUID(grn_id),
    )
    owner = (await db.execute(stmt)).scalar_one_or_none()
    if owner is None:
        raise HTTPException(status_code=404, detail="GRN not found.")
    rows = (
        await db.execute(
            select(GrnLine)
            .where(GrnLine.grn_id == uuid.UUID(grn_id))
            .order_by(GrnLine.purchase_order_line_id)
        )
    ).scalars().all()
    return [
        {
            "grn_line_id": str(ln.id),
            "purchase_order_line_id": str(ln.purchase_order_line_id),
            "item_id": str(ln.item_id),
            "qty_received": format(ln.qty_received, "f"),
            "qty_accepted": format(ln.qty_accepted, "f"),
            "qty_rejected": format(ln.qty_rejected, "f"),
        }
        for ln in rows
    ]


@router.post("/grns/{grn_id}/inspect", response_model=InspectGrnResponse)
async def inspect_grn(
    grn_id: str,
    payload: InspectGrnRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> InspectGrnResponse:
    _require_roles(
        current_user, {"WAREHOUSE_OPERATOR", "DEPT_HEAD_WAREHOUSE",
                        "SUPER_ADMIN"},
    )
    results_json = json.dumps(
        [
            {
                "grn_line_id": str(ln.grn_line_id),
                "qty_accepted": ln.qty_accepted,
                "qty_rejected": ln.qty_rejected,
            }
            for ln in payload.line_results
        ]
    )
    try:
        result = await db.execute(
            text(
                "SELECT fn_inspect_grn("
                "  CAST(:grn_id AS uuid),"
                "  CAST(:line_results AS jsonb)"
                ") AS rpc"
            ),
            {"grn_id": grn_id, "line_results": results_json},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return InspectGrnResponse(
            grn_id=rpc["grn_id"],
            total_accepted_value=str(rpc["total_accepted_value"]),
            any_rejected=rpc["any_rejected"],
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


# ---------------------------------------------------------------------------
# AP bills + 3-way match
# ---------------------------------------------------------------------------


@router.post("/bills", response_model=CreateApBillResponse, status_code=201)
async def create_ap_bill(
    payload: CreateApBillRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> CreateApBillResponse:
    _require_roles(current_user, FINANCE_ROLES)
    lines_json = json.dumps(
        [
            {
                "item_id": str(ln.item_id),
                "qty": ln.qty,
                "unit_price": ln.unit_price,
            }
            for ln in payload.lines
        ]
    )
    try:
        result = await db.execute(
            text(
                "SELECT fn_create_ap_bill("
                "  CAST(:grn_id AS uuid),"
                "  CAST(:bill_number AS varchar),"
                "  CAST(:bill_date AS date),"
                "  CAST(:lines AS jsonb),"
                "  CAST(:tax_rate_pct AS numeric)"
                ") AS rpc"
            ),
            {
                "grn_id": payload.grn_id,
                "bill_number": payload.bill_number,
                "bill_date": payload.bill_date,
                "lines": lines_json,
                "tax_rate_pct": payload.tax_rate_pct,
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return CreateApBillResponse(
            ap_bill_id=rpc["ap_bill_id"],
            total_amount=str(rpc["total_amount"]),
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.get("/bills", response_model=list[dict])
async def list_ap_bills(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    stmt = (
        select(ApBill)
        .where(ApBill.entity_id == current_user["entity_id"])
        .order_by(ApBill.bill_date.desc())
        .limit(100)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(b.id),
            "bill_number": b.bill_number,
            "status": str(b.status),
            "total_amount": str(b.total_amount),
            "paid_amount": str(b.paid_amount),
            "dispute_reason": b.dispute_reason,
        }
        for b in rows
    ]


@router.post(
    "/bills/{bill_id}/match", response_model=MatchApBillResponse
)
async def match_ap_bill(
    bill_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> MatchApBillResponse:
    _require_roles(current_user, FINANCE_ROLES)
    try:
        result = await db.execute(
            text(
                "SELECT fn_match_and_approve_ap_bill("
                "  CAST(:bill_id AS uuid)"
                ") AS rpc"
            ),
            {"bill_id": bill_id},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return MatchApBillResponse(
            status=rpc["status"],
            price_variance=(
                str(rpc["price_variance"])
                if rpc.get("price_variance") is not None
                else None
            ),
            reason=rpc.get("reason"),
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


# ---------------------------------------------------------------------------
# AP payments
# ---------------------------------------------------------------------------


@router.post("/payments", response_model=ApPaymentResponse, status_code=201)
async def record_ap_payment(
    payload: ApPaymentRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> ApPaymentResponse:
    _require_roles(current_user, FINANCE_ROLES)
    allocations_json = (
        json.dumps(payload.allocations)
        if payload.allocations
        else None
    )
    try:
        result = await db.execute(
            text(
                "SELECT fn_record_ap_payment("
                "  CAST(:vendor_id AS uuid),"
                "  CAST(:payment_date AS date),"
                "  CAST(:amount AS numeric),"
                "  CAST(:payment_method AS varchar),"
                "  CAST(:allocations AS jsonb)"
                ") AS rpc"
            ),
            {
                "vendor_id": payload.vendor_id,
                "payment_date": payload.payment_date,
                "amount": payload.amount,
                "payment_method": payload.payment_method,
                "allocations": allocations_json,
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return ApPaymentResponse(
            ap_payment_id=rpc["ap_payment_id"],
            journal_entry_id=rpc["journal_entry_id"],
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


# ---------------------------------------------------------------------------
# Module 5A: Purchase Return (Debit Note) & Landed Cost
# ---------------------------------------------------------------------------


@router.post(
    "/returns",
    response_model=PurchaseReturnResponse,
    status_code=201,
)
async def create_purchase_return(
    payload: PurchaseReturnCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> PurchaseReturnResponse:
    """Create a DRAFT purchase return linked to a GRN."""
    _require_roles(current_user, PROCUREMENT_ROLES)
    ret = PurchaseReturn(
        entity_id=current_user["entity_id"],
        vendor_id=payload.vendor_id,
        grn_id=payload.grn_id,
        warehouse_id=payload.warehouse_id,
        return_number=payload.return_number,
        return_date=payload.return_date,
        reason=payload.reason,
        created_by=current_user["user_id"],
    )
    db.add(ret)
    try:
        await db.flush()
        for line in payload.lines:
            qty = Decimal(line.qty_returned)
            price = Decimal(line.unit_price)
            db.add(
                PurchaseReturnLine(
                    purchase_return_id=ret.id,
                    grn_line_id=line.grn_line_id,
                    item_id=line.item_id,
                    qty_returned=qty,
                    unit_price=price,
                    line_total=round(qty * price, 2),
                )
            )
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        if "unique" in str(exc.orig).lower():  # type: ignore[union-attr]
            raise HTTPException(
                status_code=409,
                detail=f"Return number {payload.return_number} "
                "already exists.",
            ) from exc
        raise
    await db.refresh(ret)
    return PurchaseReturnResponse(
        id=ret.id,
        return_number=ret.return_number,
        status=str(ret.status),
        total_amount=str(ret.total_amount),
        lines=[],
    )


@router.get("/returns", response_model=list[dict])
async def list_purchase_returns(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    stmt = (
        select(PurchaseReturn)
        .where(
            PurchaseReturn.entity_id == current_user["entity_id"]
        )
        .order_by(PurchaseReturn.return_date.desc())
        .limit(100)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "return_number": r.return_number,
            "status": str(r.status),
            "total_amount": str(r.total_amount),
            "reason": r.reason,
        }
        for r in rows
    ]


@router.post(
    "/returns/{return_id}/approve",
    response_model=ApprovePurchaseReturnResponse,
)
async def approve_purchase_return(
    return_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> ApprovePurchaseReturnResponse:
    """Approve DRAFT return: issue stock out + debit note GL."""
    _require_roles(
        current_user,
        {
            "DEPT_HEAD_WAREHOUSE",
            "FINANCE_OPERATOR",
            "DEPT_HEAD_FA",
            "SUPER_ADMIN",
        },
    )
    try:
        result = await db.execute(
            text(
                "SELECT fn_approve_purchase_return("
                "  CAST(:return_id AS uuid)"
                ") AS rpc"
            ),
            {"return_id": return_id},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return ApprovePurchaseReturnResponse(
            purchase_return_id=rpc["purchase_return_id"],
            return_number=rpc["return_number"],
            subtotal=str(rpc["subtotal"]),
            tax_amount=str(rpc["tax_amount"]),
            total_amount=str(rpc["total_amount"]),
            journal_entry_id=rpc["journal_entry_id"],
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.post(
    "/landed-costs",
    response_model=LandedCostResponse,
    status_code=201,
)
async def create_landed_cost(
    payload: LandedCostCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> LandedCostResponse:
    """Create a DRAFT landed cost record against a GRN."""
    _require_roles(current_user, FINANCE_ROLES)
    method = payload.allocation_method
    if method not in ("BY_VALUE", "BY_QTY", "BY_WEIGHT"):
        raise HTTPException(
            status_code=422,
            detail="allocation_method must be BY_VALUE, BY_QTY, "
            "or BY_WEIGHT.",
        )
    lc = LandedCost(
        entity_id=current_user["entity_id"],
        grn_id=payload.grn_id,
        lc_number=payload.lc_number,
        lc_date=payload.lc_date,
        vendor_id=payload.vendor_id,
        description=payload.description,
        total_amount=Decimal(payload.total_amount),
        allocation_method=LandedCostAllocMethodEnum(method),
        created_by=current_user["user_id"],
    )
    db.add(lc)
    try:
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        if "unique" in str(exc.orig).lower():  # type: ignore[union-attr]
            raise HTTPException(
                status_code=409,
                detail=f"Landed cost number {payload.lc_number} "
                "already exists.",
            ) from exc
        raise
    await db.refresh(lc)
    return LandedCostResponse(
        id=lc.id,
        lc_number=lc.lc_number,
        status=str(lc.status),
        total_amount=str(lc.total_amount),
        allocation_method=str(lc.allocation_method),
    )


@router.get("/landed-costs", response_model=list[dict])
async def list_landed_costs(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    stmt = (
        select(LandedCost)
        .where(LandedCost.entity_id == current_user["entity_id"])
        .order_by(LandedCost.lc_date.desc())
        .limit(100)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "lc_number": r.lc_number,
            "status": str(r.status),
            "total_amount": str(r.total_amount),
            "allocation_method": str(r.allocation_method),
            "description": r.description,
        }
        for r in rows
    ]


@router.post(
    "/landed-costs/{lc_id}/allocate",
    response_model=AllocateLandedCostResponse,
)
async def allocate_landed_cost(
    lc_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> AllocateLandedCostResponse:
    """Allocate DRAFT landed cost: capitalize HPP + GL posting."""
    _require_roles(current_user, FINANCE_ROLES)
    try:
        result = await db.execute(
            text(
                "SELECT fn_allocate_landed_cost("
                "  CAST(:lc_id AS uuid)"
                ") AS rpc"
            ),
            {"lc_id": lc_id},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return AllocateLandedCostResponse(
            landed_cost_id=rpc["landed_cost_id"],
            lc_number=rpc["lc_number"],
            total_allocated=str(rpc["total_allocated"]),
            lines_count=rpc["lines_count"],
            journal_entry_id=rpc["journal_entry_id"],
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc
