"""
Budgeting & Analytics Pydantic schemas (Module 8).

Amounts are strings in JSON (Decimal precision).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class BudgetLineIn(BaseModel):
    account_id: uuid.UUID
    department_code: str | None = None
    period_month: int = Field(ge=1, le=12)
    budgeted_amount: str


class CreateBudgetRequest(BaseModel):
    fiscal_year_id: uuid.UUID
    budget_name: str = Field(min_length=1, max_length=150)
    lines: list[BudgetLineIn] = Field(min_length=1)


class CreateBudgetResponse(BaseModel):
    budget_id: uuid.UUID


class BudgetStatusResponse(BaseModel):
    budget_id: uuid.UUID
    status: str


class ReviseBudgetRequest(BaseModel):
    reason: str = Field(min_length=1)
    lines: list[BudgetLineIn] = Field(min_length=1)


class ReviseBudgetResponse(BaseModel):
    budget_id: uuid.UUID
    revision_number: int


class BudgetVsActualRow(BaseModel):
    account_code: str
    account_name: str
    department_code: str | None = None
    budgeted_amount: str
    actual_amount: str
    variance_amount: str
    variance_pct: str | None = None


class MonthlyTrendRow(BaseModel):
    period_year: int
    period_month: int
    total_amount: str


class ProductivityBatchResponse(BaseModel):
    metrics_calculated: int
