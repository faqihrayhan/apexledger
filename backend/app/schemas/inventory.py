"""
Module 3 — Inventory Pydantic schemas.

Quantities and costs are strings in JSON (Decimal precision preserved).
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.inventory import (
    CostingMethodEnum,
    ItemTypeEnum,
    WoStatusEnum,
)


class WarehouseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    warehouse_type: str = "OUTLET"


class WarehouseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    warehouse_type: str
    is_active: bool


class ItemCreate(BaseModel):
    item_code: str = Field(min_length=1, max_length=30)
    item_name: str = Field(min_length=1, max_length=150)
    item_type: ItemTypeEnum
    costing_method: CostingMethodEnum = CostingMethodEnum.MOVING_AVERAGE
    uom_base: str = Field(min_length=1, max_length=10)
    requires_fefo: bool = False
    gl_inventory_account_id: uuid.UUID | None = None
    gl_cogs_account_id: uuid.UUID | None = None


class ItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_code: str
    item_name: str
    item_type: ItemTypeEnum
    costing_method: CostingMethodEnum
    uom_base: str
    requires_fefo: bool
    is_active: bool
    gl_inventory_account_id: uuid.UUID | None
    gl_cogs_account_id: uuid.UUID | None


class ReceiveStockRequest(BaseModel):
    item_id: uuid.UUID
    warehouse_id: uuid.UUID
    qty: str
    unit_cost: str
    reference_type: str = "GRN"
    reference_id: uuid.UUID | None = None
    expiry_date: date | None = None


class ReceiveStockResponse(BaseModel):
    transaction_id: uuid.UUID
    qty: str
    unit_cost: str


class IssueStockRequest(BaseModel):
    item_id: uuid.UUID
    warehouse_id: uuid.UUID
    qty: str
    reference_type: str = "MANUAL"
    reference_id: uuid.UUID | None = None


class IssueStockResponse(BaseModel):
    transaction_id: uuid.UUID
    qty: str
    total_cost: str
    weighted_unit_cost: str


class TransferStockRequest(BaseModel):
    item_id: uuid.UUID
    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID
    qty: str


class TransferStockResponse(BaseModel):
    qty_transferred: str
    unit_cost: str


class WorkOrderCreate(BaseModel):
    bom_id: uuid.UUID
    item_id: uuid.UUID
    warehouse_id: uuid.UUID
    wo_number: str = Field(min_length=1, max_length=30)
    qty_planned: str
    cost_center_id: uuid.UUID | None = None
    direct_labor_cost: str = "0"
    gl_accrued_labor_account_id: uuid.UUID | None = None
    driver_qty_used: str = "0"


class WorkOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    wo_number: str
    bom_id: uuid.UUID
    item_id: uuid.UUID
    warehouse_id: uuid.UUID
    cost_center_id: uuid.UUID | None
    qty_planned: str
    qty_produced: str | None
    status: WoStatusEnum
    journal_entry_id: uuid.UUID | None


class CompleteWorkOrderRequest(BaseModel):
    qty_produced: str


class CompleteWorkOrderResponse(BaseModel):
    work_order_id: uuid.UUID
    cogm: str
    unit_cost: str
    material_cost: str
    foh_allocated: str
