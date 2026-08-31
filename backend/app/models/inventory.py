"""
Module 3 — Universal Costing & Inventory ORM models.

Covers: warehouses, items, stock lots, aggregate stock, the immutable
stock ledger, BOMs + components, cost centers, and work orders.

All mutations flow through the PL/pgSQL RPCs (receive/issue/transfer/
complete-WO); ORM models serve typed reads and app-level entity
filtering (dual-layer defense).
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
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class ItemTypeEnum(enum.StrEnum):
    RAW_MATERIAL = "RAW_MATERIAL"
    FINISHED_GOOD = "FINISHED_GOOD"
    SERVICE = "SERVICE"
    BUNDLE = "BUNDLE"


class CostingMethodEnum(enum.StrEnum):
    FIFO = "FIFO"
    MOVING_AVERAGE = "MOVING_AVERAGE"


class StockTxnTypeEnum(enum.StrEnum):
    RECEIPT = "RECEIPT"
    ISSUE = "ISSUE"
    TRANSFER_OUT = "TRANSFER_OUT"
    TRANSFER_IN = "TRANSFER_IN"
    ADJUSTMENT = "ADJUSTMENT"
    WO_CONSUMPTION = "WO_CONSUMPTION"
    WO_OUTPUT = "WO_OUTPUT"


class WoStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"


class BomTypeEnum(enum.StrEnum):
    RECIPE = "RECIPE"
    KIT = "KIT"
    ROUTING = "ROUTING"


class Warehouse(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "warehouses"
    __table_args__ = (UniqueConstraint("entity_id", "code"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    warehouse_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="OUTLET"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class Item(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("entity_id", "item_code"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    item_code: Mapped[str] = mapped_column(String(30), nullable=False)
    item_name: Mapped[str] = mapped_column(String(150), nullable=False)
    item_type: Mapped[str] = mapped_column(
        Enum(ItemTypeEnum, name="item_type_enum"), nullable=False
    )
    costing_method: Mapped[str] = mapped_column(
        Enum(CostingMethodEnum, name="costing_method_enum"),
        nullable=False,
        default=CostingMethodEnum.MOVING_AVERAGE,
    )
    uom_base: Mapped[str] = mapped_column(String(10), nullable=False)
    requires_fefo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    gl_inventory_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id")
    )
    gl_cogs_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class StockLot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "stock_lots"

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    lot_number: Mapped[str | None] = mapped_column(String(30))
    qty_received: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    qty_remaining: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    received_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    expiry_date: Mapped[date | None] = mapped_column(Date)


class ItemWarehouseStock(Base):
    __tablename__ = "item_warehouse_stock"

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), primary_key=True
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), primary_key=True
    )
    qty_on_hand: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False, default=0
    )
    avg_cost: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False, default=0
    )


class StockTransaction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "stock_transactions"

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    transaction_type: Mapped[str] = mapped_column(
        Enum(StockTxnTypeEnum, name="stock_txn_type_enum"), nullable=False
    )
    qty: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    total_cost: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(30))
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    transaction_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False
    )


class Bom(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "boms"
    __table_args__ = (UniqueConstraint("item_id", "version"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    bom_type: Mapped[str] = mapped_column(
        Enum(BomTypeEnum, name="bom_type_enum"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    yield_qty: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False, default=1
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class BomComponent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "bom_components"

    bom_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boms.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    qty_per_yield: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    waste_pct: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )
    sequence_no: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1
    )


class CostCenter(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "cost_centers"
    __table_args__ = (UniqueConstraint("entity_id", "code"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    total_estimated_overhead: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    total_capacity_driver: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False, default=0
    )
    driver_unit: Mapped[str] = mapped_column(
        String(20), nullable=False, default="LABOR_HOURS"
    )
    gl_foh_applied_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class WorkOrder(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "work_orders"
    __table_args__ = (UniqueConstraint("entity_id", "wo_number"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    wo_number: Mapped[str] = mapped_column(String(30), nullable=False)
    bom_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boms.id"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    cost_center_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cost_centers.id")
    )
    qty_planned: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    qty_produced: Mapped[float | None] = mapped_column(Numeric(18, 4))
    direct_labor_cost: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    gl_accrued_labor_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id")
    )
    driver_qty_used: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False, default=0
    )
    status: Mapped[str] = mapped_column(
        Enum(WoStatusEnum, name="wo_status_enum"),
        nullable=False,
        default=WoStatusEnum.DRAFT,
    )
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
