"""
Module 6 — Treasury & Cash Management Pydantic schemas.

Amounts are strings in JSON (Decimal precision).
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class BankAccountCreate(BaseModel):
    bank_name: str = Field(min_length=1, max_length=100)
    account_number: str = Field(min_length=1, max_length=30)
    account_name: str = Field(min_length=1, max_length=150)
    currency_code: str = "IDR"
    gl_account_id: uuid.UUID


class BankAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bank_name: str
    account_number: str
    account_name: str
    currency_code: str
    is_active: bool


class KasbonLineIn(BaseModel):
    expense_account_id: uuid.UUID
    description: str = Field(min_length=1, max_length=200)
    amount: str
    receipt_reference: str | None = None


class KasbonCreate(BaseModel):
    department_code: str | None = None
    amount: str
    purpose: str = Field(min_length=3, max_length=500)
    request_date: date


class KasbonResponse(BaseModel):
    id: uuid.UUID
    status: str
    amount: str
    purpose: str
    required_approval_role: str | None = None


class SubmitKasbonResponse(BaseModel):
    kasbon_request_id: uuid.UUID
    required_approval_role: str


class ApproveKasbonResponse(BaseModel):
    kasbon_request_id: uuid.UUID
    status: str


class DisburseKasbonRequest(BaseModel):
    bank_account_id: uuid.UUID
    piutang_karyawan_account_id: uuid.UUID


class DisburseKasbonResponse(BaseModel):
    kasbon_request_id: uuid.UUID
    journal_entry_id: uuid.UUID


class SettleKasbonRequest(BaseModel):
    settlement_date: date
    piutang_karyawan_account_id: uuid.UUID
    bank_account_id: uuid.UUID
    lines: list[KasbonLineIn] = Field(min_length=1)


class SettleKasbonResponse(BaseModel):
    settlement_id: uuid.UUID
    actual_used: str
    refund: str
    additional_claim: str
    journal_entry_id: uuid.UUID


class BankStatementLineIn(BaseModel):
    statement_date: date
    description: str | None = None
    amount: str


class ImportStatementRequest(BaseModel):
    lines: list[BankStatementLineIn] = Field(min_length=1)


class AutoMatchResponse(BaseModel):
    matched_count: int


class ForecastRow(BaseModel):
    week_start: date
    category: str
    source_type: str
    estimated_amount: str
