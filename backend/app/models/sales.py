"""
Module 4 — Omnichannel Sales & AR ORM models.

Covers: entity GL defaults, customers, sales orders + lines,
delivery orders + lines, AR invoices + lines, AR payments +
allocations, POS transactions + lines.

All mutations flow through the PL/pgSQL RPCs; ORM models serve
typed reads and app-level entity filtering (dual-layer defense).
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class SoStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class DoStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"


class ArInvoiceStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class EntityGlDefaults(Base):
    __tablename__ = "entity_gl_defaults"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), primary_key=True
    )
    gl_ar_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id"), nullable=False
    )
    gl_sales_revenue_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id"), nullable=False
    )
    gl_ppn_keluaran_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id"), nullable=False
    )
    gl_kas_bank_default_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id"), nullable=False
    )


class Customer(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("entity_id", "customer_code"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    customer_code: Mapped[str] = mapped_column(String(20), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(150), nullable=False)
    credit_limit: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    payment_term_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=30
    )
    npwp: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class SalesOrder(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sales_orders"
    __table_args__ = (UniqueConstraint("entity_id", "so_number"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    so_number: Mapped[str] = mapped_column(String(30), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(SoStatusEnum, name="so_status_enum"),
        nullable=False,
        default=SoStatusEnum.DRAFT,
    )
    total_amount: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class SalesOrderLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sales_order_lines"

    sales_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sales_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    qty_ordered: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    qty_delivered: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False, default=0
    )
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)


class DeliveryOrder(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "delivery_orders"
    __table_args__ = (UniqueConstraint("entity_id", "do_number"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    sales_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_orders.id"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    do_number: Mapped[str] = mapped_column(String(30), nullable=False)
    delivery_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(DoStatusEnum, name="do_status_enum"),
        nullable=False,
        default=DoStatusEnum.DRAFT,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class DeliveryOrderLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "delivery_order_lines"

    delivery_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("delivery_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    sales_order_line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_order_lines.id"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    qty_delivered: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False, default=0
    )
    total_cost: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )


class ArInvoice(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ar_invoices"
    __table_args__ = (UniqueConstraint("entity_id", "invoice_number"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    delivery_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_orders.id")
    )
    invoice_number: Mapped[str] = mapped_column(String(30), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(ArInvoiceStatusEnum, name="ar_invoice_status_enum"),
        nullable=False,
        default=ArInvoiceStatusEnum.DRAFT,
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
    efaktur_number: Mapped[str | None] = mapped_column(String(30))
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class ArInvoiceLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ar_invoice_lines"

    ar_invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ar_invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    qty: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)


class ArPayment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ar_payments"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class ArPaymentAllocation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ar_payment_allocations"

    allocation_date: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today
    )
    ar_payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ar_payments.id", ondelete="CASCADE"),
        nullable=False,
    )
    ar_invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ar_invoices.id"), nullable=False
    )
    allocated_amount: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class PosTransaction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "pos_transactions"
    __table_args__ = (
        UniqueConstraint("entity_id", "transaction_number"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    transaction_number: Mapped[str] = mapped_column(String(30), nullable=False)
    transaction_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    total_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    cashier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False
    )
    is_synced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class PosTransactionLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "pos_transaction_lines"

    pos_transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pos_transactions.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    qty: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)


class SalesReturnStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"


class SalesReturn(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sales_returns"
    __table_args__ = (UniqueConstraint("entity_id", "return_number"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    ar_invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ar_invoices.id"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    return_number: Mapped[str] = mapped_column(String(30), nullable=False)
    return_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(SalesReturnStatusEnum, name="sales_return_status_enum"),
        nullable=False,
        default=SalesReturnStatusEnum.DRAFT,
    )
    reason: Mapped[str] = mapped_column(String, nullable=False)
    subtotal: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    tax_amount: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    total_amount: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id")
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class SalesReturnLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sales_return_lines"

    sales_return_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sales_returns.id", ondelete="CASCADE"),
        nullable=False,
    )
    ar_invoice_line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ar_invoice_lines.id"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    qty_returned: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False
    )
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
