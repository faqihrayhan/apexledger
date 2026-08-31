"""
Module 4 — Sales & AR Pydantic schemas.

Amounts and quantities are strings in JSON (Decimal precision).
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.sales import (
    SoStatusEnum,
)


class EntityGlDefaultsUpsert(BaseModel):
    gl_ar_account_id: uuid.UUID
    gl_sales_revenue_account_id: uuid.UUID
    gl_ppn_keluaran_account_id: uuid.UUID
    gl_kas_bank_default_account_id: uuid.UUID


class CustomerCreate(BaseModel):
    customer_code: str = Field(min_length=1, max_length=20)
    customer_name: str = Field(min_length=1, max_length=150)
    credit_limit: str = "0"
    payment_term_days: int = 30
    npwp: str | None = None


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_code: str
    customer_name: str
    credit_limit: str
    payment_term_days: int
    npwp: str | None
    is_active: bool


class SoLineIn(BaseModel):
    item_id: uuid.UUID
    qty_ordered: str
    unit_price: str


class SalesOrderCreate(BaseModel):
    customer_id: uuid.UUID
    warehouse_id: uuid.UUID
    so_number: str = Field(min_length=1, max_length=30)
    order_date: date
    lines: list[SoLineIn] = Field(min_length=1)


class SoLineOut(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    qty_ordered: str
    qty_delivered: str
    unit_price: str
    line_total: str


class SalesOrderResponse(BaseModel):
    id: uuid.UUID
    so_number: str
    customer_id: uuid.UUID
    warehouse_id: uuid.UUID
    order_date: date
    status: SoStatusEnum
    total_amount: str
    lines: list[SoLineOut]


class ConfirmSoResponse(BaseModel):
    sales_order_id: uuid.UUID
    status: str


class DoLineIn(BaseModel):
    sales_order_line_id: uuid.UUID
    qty_delivered: str


class CreateDeliveryOrderRequest(BaseModel):
    delivery_date: date
    lines: list[DoLineIn] = Field(min_length=1)


class DeliveryOrderResponse(BaseModel):
    delivery_order_id: uuid.UUID
    do_number: str
    so_status: str


class IssueArInvoiceRequest(BaseModel):
    tax_rate_pct: str = "11"


class IssueArInvoiceResponse(BaseModel):
    invoice_id: uuid.UUID
    invoice_number: str
    total_amount: str
    cogs: str


class RecordArPaymentRequest(BaseModel):
    customer_id: uuid.UUID
    amount: str
    payment_date: date
    payment_method: str
    allocations: list[dict] | None = None


class RecordArPaymentResponse(BaseModel):
    payment_id: uuid.UUID
    amount: str


class PosLineIn(BaseModel):
    item_id: uuid.UUID
    qty: str
    unit_price: str


class ProcessPosSaleRequest(BaseModel):
    warehouse_id: uuid.UUID
    payment_method: str
    lines: list[PosLineIn] = Field(min_length=1)


class ProcessPosSaleResponse(BaseModel):
    pos_transaction_id: uuid.UUID
    transaction_number: str
    total_amount: str
    total_cogs: str


class PosBatchResponse(BaseModel):
    txn_count: int
    total_sales: str | None = None
    total_cogs: str | None = None
    journal_entry_id: uuid.UUID | None = None
    note: str | None = None


class SalesReturnLineIn(BaseModel):
    ar_invoice_line_id: uuid.UUID
    item_id: uuid.UUID
    qty_returned: str
    unit_price: str
    line_total: str


class SalesReturnCreate(BaseModel):
    customer_id: uuid.UUID
    ar_invoice_id: uuid.UUID
    warehouse_id: uuid.UUID
    return_number: str = Field(min_length=1, max_length=30)
    return_date: date
    reason: str
    lines: list[SalesReturnLineIn] = Field(min_length=1)


class SalesReturnResponse(BaseModel):
    id: uuid.UUID
    return_number: str
    status: str
    total_amount: str


class ApproveSalesReturnResponse(BaseModel):
    sales_return_id: uuid.UUID
    return_number: str
    total_amount: str
    cogs_reversed: str
