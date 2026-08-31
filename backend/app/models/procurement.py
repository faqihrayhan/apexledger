"""
Module 5 — Procurement & AP (PUTG) ORM models.

Covers: vendors, purchase requests + lines, purchase orders +
lines, goods received notes + grn lines, AP bills + lines,
AP payments + allocations, approval thresholds.

All mutations flow through the PL/pgSQL RPCs; ORM models serve
typed reads and app-level entity filtering (dual-layer defense).
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.layer0 import RoleEnum


class PrStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONVERTED = "CONVERTED"


class PoStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class GrnStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    COMPLETED = "COMPLETED"


class InspectionStatusEnum(enum.StrEnum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"


class ApBillStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    MATCHED = "MATCHED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class ApprovalDocTypeEnum(enum.StrEnum):
    KASBON = "KASBON"
    PO = "PO"


class Vendor(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "vendors"
    __table_args__ = (UniqueConstraint("entity_id", "vendor_code"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    vendor_code: Mapped[str] = mapped_column(String(20), nullable=False)
    vendor_name: Mapped[str] = mapped_column(String(150), nullable=False)
    payment_term_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=30
    )
    npwp: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )


class PurchaseRequest(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "purchase_requests"
    __table_args__ = (UniqueConstraint("entity_id", "pr_number"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    department_code: Mapped[str | None] = mapped_column(String(30))
    pr_number: Mapped[str] = mapped_column(String(30), nullable=False)
    request_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(PrStatusEnum, name="pr_status_enum"), nullable=False,
        default=PrStatusEnum.DRAFT,
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"),
        nullable=False,
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id")
    )


class PurchaseRequestLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "purchase_request_lines"

    pr_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    qty_requested: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False
    )
    estimated_unit_price: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )


class PurchaseOrder(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("entity_id", "po_number"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    pr_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_requests.id")
    )
    po_number: Mapped[str] = mapped_column(String(30), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(PoStatusEnum, name="po_status_enum"), nullable=False,
        default=PoStatusEnum.DRAFT,
    )
    required_approval_role: Mapped[RoleEnum | None] = mapped_column(
        Enum(RoleEnum, name="role_enum")
    )
    total_amount: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"),
        nullable=False,
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id")
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class PurchaseOrderLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "purchase_order_lines"

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    qty_ordered: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False
    )
    qty_received: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False, default=0
    )
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)


class GoodsReceivedNote(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "goods_received_notes"
    __table_args__ = (UniqueConstraint("entity_id", "grn_number"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"),
        nullable=False,
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    grn_number: Mapped[str] = mapped_column(String(30), nullable=False)
    received_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(GrnStatusEnum, name="grn_status_enum"), nullable=False,
        default=GrnStatusEnum.DRAFT,
    )
    inspection_status: Mapped[str] = mapped_column(
        Enum(InspectionStatusEnum, name="inspection_status_enum"),
        nullable=False, default=InspectionStatusEnum.PENDING,
    )
    inspected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id")
    )
    inspected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"),
        nullable=False,
    )


class GrnLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "grn_lines"

    grn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("goods_received_notes.id", ondelete="CASCADE"),
        nullable=False,
    )
    purchase_order_line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_order_lines.id"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    qty_received: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False
    )
    qty_accepted: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False, default=0
    )
    qty_rejected: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False, default=0
    )


class ApBill(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ap_bills"
    __table_args__ = (UniqueConstraint("entity_id", "bill_number"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False
    )
    grn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goods_received_notes.id"),
        nullable=False,
    )
    bill_number: Mapped[str] = mapped_column(String(30), nullable=False)
    bill_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(ApBillStatusEnum, name="ap_bill_status_enum"),
        nullable=False, default=ApBillStatusEnum.DRAFT,
    )
    subtotal: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    tax_amount: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    total_amount: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    paid_amount: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    dispute_reason: Mapped[str | None] = mapped_column(Text)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id")
    )


class ApBillLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ap_bill_lines"

    ap_bill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ap_bills.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    qty: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)


class ApPayment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ap_payments"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"),
        nullable=False,
    )


class ApPaymentAllocation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ap_payment_allocations"

    ap_payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ap_payments.id", ondelete="CASCADE"),
        nullable=False,
    )
    ap_bill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ap_bills.id"), nullable=False
    )
    allocated_amount: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False
    )


class ApprovalThreshold(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "approval_thresholds"
    __table_args__ = (
        UniqueConstraint("entity_id", "document_type", "min_amount"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    document_type: Mapped[str] = mapped_column(String(20), nullable=False)
    min_amount: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    required_role: Mapped[str] = mapped_column(String(30), nullable=False)


class PurchaseReturnStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"


class LandedCostAllocMethodEnum(enum.StrEnum):
    BY_VALUE = "BY_VALUE"
    BY_QTY = "BY_QTY"
    BY_WEIGHT = "BY_WEIGHT"


class LandedCostStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    ALLOCATED = "ALLOCATED"
    CANCELLED = "CANCELLED"


class PurchaseReturn(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "purchase_returns"
    __table_args__ = (
        UniqueConstraint("entity_id", "return_number"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False
    )
    grn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("goods_received_notes.id"),
        nullable=False,
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    return_number: Mapped[str] = mapped_column(
        String(30), nullable=False
    )
    return_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PurchaseReturnStatusEnum] = mapped_column(
        Enum(PurchaseReturnStatusEnum, name="purchase_return_status_enum"),
        nullable=False,
        default=PurchaseReturnStatusEnum.DRAFT,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"),
        nullable=False,
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id")
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class PurchaseReturnLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "purchase_return_lines"

    purchase_return_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_returns.id", ondelete="CASCADE"),
        nullable=False,
    )
    grn_line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grn_lines.id"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    qty_returned: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )


class LandedCost(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "landed_costs"
    __table_args__ = (UniqueConstraint("entity_id", "lc_number"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    grn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("goods_received_notes.id"),
        nullable=False,
    )
    lc_number: Mapped[str] = mapped_column(String(30), nullable=False)
    lc_date: Mapped[date] = mapped_column(Date, nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id")
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    allocation_method: Mapped[LandedCostAllocMethodEnum] = mapped_column(
        Enum(LandedCostAllocMethodEnum,
             name="landed_cost_alloc_method_enum"),
        nullable=False,
        default=LandedCostAllocMethodEnum.BY_VALUE,
    )
    status: Mapped[LandedCostStatusEnum] = mapped_column(
        Enum(LandedCostStatusEnum, name="landed_cost_status_enum"),
        nullable=False,
        default=LandedCostStatusEnum.DRAFT,
    )
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"),
        nullable=False,
    )


class LandedCostLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "landed_cost_lines"

    landed_cost_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("landed_costs.id", ondelete="CASCADE"),
        nullable=False,
    )
    grn_line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grn_lines.id"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    allocated_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
