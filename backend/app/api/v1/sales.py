"""
Sales & AR API routes (Module 4).

RPC wrappers for the sales flow (confirm SO -> create DO ->
issue invoice -> record payment -> POS) + typed reads. Business
rules live in the PL/pgSQL RPCs; this layer validates, scopes,
and maps errors.

Role model (PRD 4.6):
- confirm SO: SALES_OPERATOR, DEPT_HEAD_SALES, SUPER_ADMIN
- create DO: WAREHOUSE_OPERATOR, DEPT_HEAD_WAREHOUSE, SUPER_ADMIN
- issue invoice / record payment: FINANCE_OPERATOR, DEPT_HEAD_FA, SUPER_ADMIN
- POS: SALES_OPERATOR, SUPER_ADMIN
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
from app.models.sales import (
    ArInvoice,
    Customer,
    EntityGlDefaults,
    SalesOrder,
    SalesOrderLine,
    SalesReturn,
    SalesReturnLine,
)
from app.schemas.sales import (
    ApproveSalesReturnResponse,
    ConfirmSoResponse,
    CreateDeliveryOrderRequest,
    CustomerCreate,
    CustomerResponse,
    DeliveryOrderResponse,
    EntityGlDefaultsUpsert,
    IssueArInvoiceRequest,
    IssueArInvoiceResponse,
    PosBatchResponse,
    ProcessPosSaleRequest,
    ProcessPosSaleResponse,
    RecordArPaymentRequest,
    RecordArPaymentResponse,
    SalesOrderCreate,
    SalesOrderResponse,
    SalesReturnCreate,
    SalesReturnResponse,
    SoLineOut,
)

router = APIRouter(prefix="/sales", tags=["Sales & AR"])

SALES_ROLES = {"SALES_OPERATOR", "DEPT_HEAD_SALES", "SUPER_ADMIN"}
WAREHOUSE_ROLES = {"WAREHOUSE_OPERATOR", "DEPT_HEAD_WAREHOUSE", "SUPER_ADMIN"}
FINANCE_ROLES = {"FINANCE_OPERATOR", "DEPT_HEAD_FA", "SUPER_ADMIN"}
POS_ROLES = {"SALES_OPERATOR", "SUPER_ADMIN"}


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
# Entity GL defaults
# ---------------------------------------------------------------------------


@router.put("/gl-defaults", status_code=200)
async def upsert_gl_defaults(
    payload: EntityGlDefaultsUpsert,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> dict:
    _require_roles(current_user, FINANCE_ROLES)

    stmt = select(EntityGlDefaults).where(
        EntityGlDefaults.entity_id == current_user["entity_id"]
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is None:
        existing = EntityGlDefaults(entity_id=current_user["entity_id"])
        db.add(existing)
    existing.gl_ar_account_id = payload.gl_ar_account_id
    existing.gl_sales_revenue_account_id = payload.gl_sales_revenue_account_id
    existing.gl_ppn_keluaran_account_id = payload.gl_ppn_keluaran_account_id
    existing.gl_kas_bank_default_account_id = payload.gl_kas_bank_default_account_id
    await db.commit()
    return {"success": True}


@router.get("/gl-defaults")
async def get_gl_defaults(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> dict:
    stmt = select(EntityGlDefaults).where(
        EntityGlDefaults.entity_id == current_user["entity_id"]
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return {"configured": False}
    return {
        "configured": True,
        "gl_ar_account_id": str(row.gl_ar_account_id),
        "gl_sales_revenue_account_id": str(row.gl_sales_revenue_account_id),
        "gl_ppn_keluaran_account_id": str(row.gl_ppn_keluaran_account_id),
        "gl_kas_bank_default_account_id": str(row.gl_kas_bank_default_account_id),
    }


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------


@router.get("/customers", response_model=list[CustomerResponse])
async def list_customers(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[CustomerResponse]:
    stmt = (
        select(Customer)
        .where(Customer.entity_id == current_user["entity_id"])
        .order_by(Customer.customer_code)
    )
    result = await db.execute(stmt)
    return [
        CustomerResponse(
            id=c.id, customer_code=c.customer_code,
            customer_name=c.customer_name,
            credit_limit=str(c.credit_limit),
            payment_term_days=c.payment_term_days,
            npwp=c.npwp, is_active=c.is_active,
        )
        for c in result.scalars().all()
    ]


@router.post("/customers", response_model=CustomerResponse, status_code=201)
async def create_customer(
    payload: CustomerCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> CustomerResponse:
    _require_roles(current_user, SALES_ROLES)

    customer = Customer(
        entity_id=current_user["entity_id"],
        customer_code=payload.customer_code,
        customer_name=payload.customer_name,
        credit_limit=Decimal(payload.credit_limit),
        payment_term_days=payload.payment_term_days,
        npwp=payload.npwp,
    )
    db.add(customer)
    try:
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        if "unique" in str(exc.orig).lower():  # type: ignore[union-attr]
            raise HTTPException(
                status_code=409,
                detail=f"Customer code {payload.customer_code} already exists.",
            ) from exc
        raise
    await db.refresh(customer)
    return CustomerResponse(
        id=customer.id, customer_code=customer.customer_code,
        customer_name=customer.customer_name,
        credit_limit=str(customer.credit_limit),
        payment_term_days=customer.payment_term_days,
        npwp=customer.npwp, is_active=customer.is_active,
    )


# ---------------------------------------------------------------------------
# Sales orders
# ---------------------------------------------------------------------------


@router.post("/orders", response_model=SalesOrderResponse, status_code=201)
async def create_sales_order(
    payload: SalesOrderCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> SalesOrderResponse:
    _require_roles(current_user, SALES_ROLES)

    total = Decimal("0")
    for line in payload.lines:
        total += Decimal(line.qty_ordered) * Decimal(line.unit_price)

    so = SalesOrder(
        entity_id=current_user["entity_id"],
        customer_id=payload.customer_id,
        warehouse_id=payload.warehouse_id,
        so_number=payload.so_number,
        order_date=payload.order_date,
        total_amount=total,
        created_by=current_user["user_id"],
    )
    db.add(so)
    try:
        await db.flush()
        for line in payload.lines:
            db.add(
                SalesOrderLine(
                    sales_order_id=so.id,
                    item_id=line.item_id,
                    qty_ordered=Decimal(line.qty_ordered),
                    unit_price=Decimal(line.unit_price),
                    line_total=Decimal(line.qty_ordered)
                    * Decimal(line.unit_price),
                )
            )
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        if "unique" in str(exc.orig).lower():  # type: ignore[union-attr]
            raise HTTPException(
                status_code=409,
                detail=f"SO number {payload.so_number} already exists.",
            ) from exc
        raise
    await db.refresh(so)
    lines_stmt = select(SalesOrderLine).where(
        SalesOrderLine.sales_order_id == so.id
    ).order_by(SalesOrderLine.id)
    lines = (await db.execute(lines_stmt)).scalars().all()
    return SalesOrderResponse(
        id=so.id, so_number=so.so_number, customer_id=so.customer_id,
        warehouse_id=so.warehouse_id, order_date=so.order_date,
        status=so.status, total_amount=str(so.total_amount),
        lines=[
            SoLineOut(
                id=ln.id, item_id=ln.item_id,
                qty_ordered=str(ln.qty_ordered),
                qty_delivered=str(ln.qty_delivered),
                unit_price=str(ln.unit_price), line_total=str(ln.line_total),
            )
            for ln in lines
        ],
    )


@router.get("/orders", response_model=list[SalesOrderResponse])
async def list_sales_orders(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[SalesOrderResponse]:
    stmt = (
        select(SalesOrder)
        .where(SalesOrder.entity_id == current_user["entity_id"])
        .order_by(SalesOrder.created_at.desc())
        .limit(100)
    )
    sos = (await db.execute(stmt)).scalars().all()
    out: list[SalesOrderResponse] = []
    for so in sos:
        lines = (
            (
                await db.execute(
                    select(SalesOrderLine)
                    .where(SalesOrderLine.sales_order_id == so.id)
                    .order_by(SalesOrderLine.id)
                )
            )
            .scalars()
            .all()
        )
        out.append(
            SalesOrderResponse(
                id=so.id, so_number=so.so_number, customer_id=so.customer_id,
                warehouse_id=so.warehouse_id, order_date=so.order_date,
                status=so.status, total_amount=str(so.total_amount),
                lines=[
                    SoLineOut(
                        id=ln.id, item_id=ln.item_id,
                        qty_ordered=str(ln.qty_ordered),
                        qty_delivered=str(ln.qty_delivered),
                        unit_price=str(ln.unit_price),
                        line_total=str(ln.line_total),
                    )
                    for ln in lines
                ],
            )
        )
    return out


@router.post("/orders/{so_id}/confirm", response_model=ConfirmSoResponse)
async def confirm_sales_order(
    so_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> ConfirmSoResponse:
    """Confirm a DRAFT sales order (credit-limit gate)."""
    _require_roles(current_user, SALES_ROLES)

    try:
        result = await db.execute(
            text(
                "SELECT fn_confirm_sales_order(CAST(:so_id AS uuid)) AS rpc"
            ),
            {"so_id": so_id},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return ConfirmSoResponse(
            sales_order_id=rpc["sales_order_id"], status=rpc["status"]
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.post(
    "/orders/{so_id}/delivery-orders",
    response_model=DeliveryOrderResponse,
)
async def create_delivery_order(
    so_id: str,
    payload: CreateDeliveryOrderRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> DeliveryOrderResponse:
    """Create a delivery order (surat jalan); issues stock per line."""
    _require_roles(current_user, WAREHOUSE_ROLES)

    lines_json = json.dumps(
        [
            {
                "sales_order_line_id": str(ln.sales_order_line_id),
                "qty_delivered": ln.qty_delivered,
            }
            for ln in payload.lines
        ]
    )
    try:
        result = await db.execute(
            text(
                "SELECT fn_create_delivery_order("
                "  CAST(:so_id AS uuid),"
                "  CAST(:delivery_date AS date),"
                "  CAST(:lines AS jsonb)"
                ") AS rpc"
            ),
            {
                "so_id": so_id,
                "delivery_date": payload.delivery_date,
                "lines": lines_json,
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return DeliveryOrderResponse(
            delivery_order_id=rpc["delivery_order_id"],
            do_number=rpc["do_number"],
            so_status=rpc.get("so_status", ""),
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.post(
    "/delivery-orders/{do_id}/invoice",
    response_model=IssueArInvoiceResponse,
)
async def issue_ar_invoice(
    do_id: str,
    payload: IssueArInvoiceRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> IssueArInvoiceResponse:
    """Issue an AR invoice from a delivered DO (3-way match + GL)."""
    _require_roles(current_user, FINANCE_ROLES)

    try:
        result = await db.execute(
            text(
                "SELECT fn_issue_ar_invoice("
                "  CAST(:do_id AS uuid), CAST(:tax AS numeric)"
                ") AS rpc"
            ),
            {"do_id": do_id, "tax": str(payload.tax_rate_pct)},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return IssueArInvoiceResponse(
            invoice_id=rpc["invoice_id"],
            invoice_number=rpc["invoice_number"],
            total_amount=str(rpc["total_amount"]),
            cogs=str(rpc["cogs"]),
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


# ---------------------------------------------------------------------------
# AR payments
# ---------------------------------------------------------------------------


@router.post("/payments", response_model=RecordArPaymentResponse)
async def record_ar_payment(
    payload: RecordArPaymentRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> RecordArPaymentResponse:
    """Record an AR payment; auto-allocates FIFO by due date when
    allocations are omitted."""
    _require_roles(current_user, FINANCE_ROLES)

    allocations_json = (
        json.dumps(payload.allocations) if payload.allocations else None
    )
    try:
        result = await db.execute(
            text(
                "SELECT fn_record_ar_payment("
                "  CAST(:customer_id AS uuid), CAST(:amount AS numeric),"
                "  CAST(:payment_date AS date), :method,"
                "  CAST(:allocations AS jsonb)"
                ") AS rpc"
            ),
            {
                "customer_id": str(payload.customer_id),
                "amount": str(payload.amount),
                "payment_date": payload.payment_date,
                "method": payload.payment_method,
                "allocations": allocations_json,
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return RecordArPaymentResponse(
            payment_id=rpc["payment_id"], amount=str(rpc["amount"])
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.get("/invoices")
async def list_invoices(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
    outstanding_only: bool = Query(default=False),
) -> list[dict]:
    stmt = (
        select(ArInvoice)
        .where(ArInvoice.entity_id == current_user["entity_id"])
        .order_by(ArInvoice.invoice_date.desc())
        .limit(100)
    )
    if outstanding_only:
        stmt = stmt.where(ArInvoice.status.in_(["ISSUED", "PARTIALLY_PAID"]))
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(inv.id),
            "invoice_number": inv.invoice_number,
            "customer_id": str(inv.customer_id),
            "status": str(inv.status),
            "subtotal": str(inv.subtotal),
            "tax_amount": str(inv.tax_amount),
            "total_amount": str(inv.total_amount),
            "paid_amount": str(inv.paid_amount),
            "due_date": str(inv.due_date),
        }
        for inv in rows
    ]


# ---------------------------------------------------------------------------
# POS
# ---------------------------------------------------------------------------


@router.post("/pos", response_model=ProcessPosSaleResponse)
async def process_pos_sale(
    payload: ProcessPosSaleRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> ProcessPosSaleResponse:
    """Fast-path POS sale (single RPC round-trip). GL is batched."""
    _require_roles(current_user, POS_ROLES)

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
                "SELECT fn_process_pos_sale("
                "  CAST(:warehouse_id AS uuid),"
                "  CAST(:lines AS jsonb), :method"
                ") AS rpc"
            ),
            {
                "warehouse_id": str(payload.warehouse_id),
                "lines": lines_json,
                "method": payload.payment_method,
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return ProcessPosSaleResponse(
            pos_transaction_id=rpc["pos_transaction_id"],
            transaction_number=rpc["transaction_number"],
            total_amount=str(rpc["total_amount"]),
            total_cogs=str(rpc["total_cogs"]),
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.post("/pos/post-batch", response_model=PosBatchResponse)
async def post_pos_batch(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> PosBatchResponse:
    """Aggregate all un-posted POS transactions into one journal entry."""
    _require_roles(current_user, FINANCE_ROLES)

    try:
        result = await db.execute(
            text(
                "SELECT fn_post_pos_batch_journal("
                "  CAST(:entity_id AS uuid)"
                ") AS rpc"
            ),
            {"entity_id": str(current_user["entity_id"])},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return PosBatchResponse(
            txn_count=rpc["txn_count"],
            total_sales=(
                str(rpc["total_sales"]) if "total_sales" in rpc else None
            ),
            total_cogs=str(rpc["total_cogs"]) if "total_cogs" in rpc else None,
            journal_entry_id=rpc.get("journal_entry_id"),
            note=rpc.get("note"),
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


# ---------------------------------------------------------------------------
# Sales returns / credit notes (Module 4A)
# ---------------------------------------------------------------------------

RETURN_APPROVE_ROLES = {"DEPT_HEAD_SALES", "FINANCE_OPERATOR", "DEPT_HEAD_FA", "SUPER_ADMIN"}


@router.post("/returns", response_model=SalesReturnResponse, status_code=201)
async def create_sales_return(
    payload: SalesReturnCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> SalesReturnResponse:
    """Create a DRAFT sales return against an issued invoice."""
    _require_roles(current_user, SALES_ROLES)

    ret = SalesReturn(
        entity_id=current_user["entity_id"],
        customer_id=payload.customer_id,
        ar_invoice_id=payload.ar_invoice_id,
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
            db.add(
                SalesReturnLine(
                    sales_return_id=ret.id,
                    ar_invoice_line_id=line.ar_invoice_line_id,
                    item_id=line.item_id,
                    qty_returned=Decimal(line.qty_returned),
                    unit_price=Decimal(line.unit_price),
                    line_total=Decimal(line.line_total),
                )
            )
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        if "unique" in str(exc.orig).lower():  # type: ignore[union-attr]
            raise HTTPException(
                status_code=409,
                detail=f"Return number {payload.return_number} already exists.",
            ) from exc
        raise
    await db.refresh(ret)
    return SalesReturnResponse(
        id=ret.id, return_number=ret.return_number,
        status=str(ret.status), total_amount=str(ret.total_amount),
    )


@router.get("/returns", response_model=list[SalesReturnResponse])
async def list_sales_returns(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[SalesReturnResponse]:
    stmt = (
        select(SalesReturn)
        .where(SalesReturn.entity_id == current_user["entity_id"])
        .order_by(SalesReturn.created_at.desc())
        .limit(100)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        SalesReturnResponse(
            id=r.id, return_number=r.return_number, status=str(r.status),
            total_amount=str(r.total_amount),
        )
        for r in rows
    ]


@router.post(
    "/returns/{ret_id}/approve", response_model=ApproveSalesReturnResponse
)
async def approve_sales_return(
    ret_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> ApproveSalesReturnResponse:
    """Approve a sales return: stock back, credit-note GL, AR cut."""
    _require_roles(current_user, RETURN_APPROVE_ROLES)

    try:
        result = await db.execute(
            text(
                "SELECT fn_approve_sales_return("
                "  CAST(:ret_id AS uuid)"
                ") AS rpc"
            ),
            {"ret_id": ret_id},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return ApproveSalesReturnResponse(
            sales_return_id=rpc["sales_return_id"],
            return_number=rpc["return_number"],
            total_amount=str(rpc["total_amount"]),
            cogs_reversed=str(rpc["cogs_reversed"]),
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc
