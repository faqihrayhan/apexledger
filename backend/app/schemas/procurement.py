"""
Module 5 — Procurement & AP Pydantic schemas.

Amounts and quantities are strings in JSON (Decimal precision).
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class VendorCreate(BaseModel):
    vendor_code: str = Field(min_length=1, max_length=20)
    vendor_name: str = Field(min_length=1, max_length=150)
    payment_term_days: int = 30
    npwp: str | None = None


class VendorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vendor_code: str
    vendor_name: str
    payment_term_days: int
    is_active: bool


class PoLineIn(BaseModel):
    item_id: uuid.UUID
    qty_ordered: str
    unit_price: str


class PoCreate(BaseModel):
    vendor_id: uuid.UUID
    warehouse_id: uuid.UUID
    po_number: str = Field(min_length=1, max_length=30)
    order_date: date
    lines: list[PoLineIn] = Field(min_length=1)


class PoLineOut(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    qty_ordered: str
    qty_received: str
    unit_price: str
    line_total: str


class PoResponse(BaseModel):
    id: uuid.UUID
    po_number: str
    status: str
    total_amount: str
    required_approval_role: str | None = None
    lines: list[PoLineOut] = Field(default_factory=list)


class SubmitPoResponse(BaseModel):
    purchase_order_id: uuid.UUID
    required_approval_role: str
    total_amount: str


class ApprovePoResponse(BaseModel):
    purchase_order_id: uuid.UUID
    status: str


class GrnLineIn(BaseModel):
    purchase_order_line_id: uuid.UUID
    qty_received: str


class ReceiveGoodsRequest(BaseModel):
    received_date: date
    lines: list[GrnLineIn] = Field(min_length=1)


class ReceiveGoodsResponse(BaseModel):
    grn_id: uuid.UUID
    grn_number: str
    inspection_status: str


class InspectLineIn(BaseModel):
    grn_line_id: uuid.UUID
    qty_accepted: str
    qty_rejected: str


class InspectGrnRequest(BaseModel):
    line_results: list[InspectLineIn] = Field(min_length=1)


class InspectGrnResponse(BaseModel):
    grn_id: uuid.UUID
    total_accepted_value: str
    any_rejected: bool


class ApBillLineIn(BaseModel):
    item_id: uuid.UUID
    qty: str
    unit_price: str


class CreateApBillRequest(BaseModel):
    grn_id: uuid.UUID
    bill_number: str = Field(min_length=1, max_length=30)
    bill_date: date
    tax_rate_pct: str = "11"
    lines: list[ApBillLineIn] = Field(min_length=1)


class CreateApBillResponse(BaseModel):
    ap_bill_id: uuid.UUID
    total_amount: str


class MatchApBillResponse(BaseModel):
    status: str
    price_variance: str | None = None
    reason: str | None = None


class ApPaymentRequest(BaseModel):
    vendor_id: uuid.UUID
    payment_date: date
    amount: str
    payment_method: str = "TRANSFER"
    allocations: list[dict] | None = None


class ApPaymentResponse(BaseModel):
    ap_payment_id: uuid.UUID
    journal_entry_id: uuid.UUID


class PurchaseReturnLineIn(BaseModel):
    grn_line_id: uuid.UUID
    item_id: uuid.UUID
    qty_returned: str
    unit_price: str


class PurchaseReturnCreate(BaseModel):
    vendor_id: uuid.UUID
    grn_id: uuid.UUID
    warehouse_id: uuid.UUID
    return_number: str = Field(min_length=1, max_length=30)
    return_date: date
    reason: str = Field(min_length=3, max_length=500)
    lines: list[PurchaseReturnLineIn] = Field(min_length=1)


class PurchaseReturnResponse(BaseModel):
    id: uuid.UUID
    return_number: str
    status: str
    total_amount: str
    lines: list[dict] = Field(default_factory=list)


class ApprovePurchaseReturnResponse(BaseModel):
    purchase_return_id: uuid.UUID
    return_number: str
    subtotal: str
    tax_amount: str
    total_amount: str
    journal_entry_id: uuid.UUID


class LandedCostCreate(BaseModel):
    grn_id: uuid.UUID
    lc_number: str = Field(min_length=1, max_length=30)
    lc_date: date
    vendor_id: uuid.UUID | None = None
    description: str = Field(min_length=3, max_length=500)
    total_amount: str
    allocation_method: str = "BY_VALUE"


class LandedCostResponse(BaseModel):
    id: uuid.UUID
    lc_number: str
    status: str
    total_amount: str
    allocation_method: str


class AllocateLandedCostResponse(BaseModel):
    landed_cost_id: uuid.UUID
    lc_number: str
    total_allocated: str
    lines_count: int
    journal_entry_id: uuid.UUID
