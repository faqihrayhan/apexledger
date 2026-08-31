"""
Module 2 — HR Payroll Pydantic schemas.

Amounts are strings in JSON (Decimal precision preserved); the API
never floats money.
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.hr import (
    EmploymentTypeEnum,
    PayrollPeriodStatusEnum,
    PtkpStatusEnum,
)


class EmployeeCreate(BaseModel):
    employee_code: str = Field(min_length=1, max_length=20)
    full_name: str = Field(min_length=1, max_length=150)
    position: str | None = None
    department_code: str | None = None
    employment_type: EmploymentTypeEnum = EmploymentTypeEnum.MONTHLY
    base_salary: str
    ptkp_status: PtkpStatusEnum = PtkpStatusEnum.TK0
    bank_account_no: str | None = None
    npwp: str | None = None
    hire_date: date
    termination_date: date | None = None
    is_active: bool = True


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_code: str
    full_name: str
    position: str | None
    department_code: str | None
    employment_type: EmploymentTypeEnum
    base_salary: str
    ptkp_status: PtkpStatusEnum
    bank_account_no: str | None
    npwp: str | None
    hire_date: date
    termination_date: date | None
    is_active: bool


class PayrollPeriodCreate(BaseModel):
    period_year: int = Field(ge=2000, le=2100)
    period_month: int = Field(ge=1, le=12)
    start_date: date
    end_date: date


class PayrollPeriodResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    period_year: int
    period_month: int
    start_date: date
    end_date: date
    status: PayrollPeriodStatusEnum
    accrual_journal_entry_id: uuid.UUID | None
    journal_entry_id: uuid.UUID | None


class CalculateRequest(BaseModel):
    employee_id: uuid.UUID
    payroll_period_id: uuid.UUID


class CalculateResponse(BaseModel):
    payroll_entry_id: uuid.UUID
    net_pay: str


class ApproveRequest(BaseModel):
    payroll_period_id: uuid.UUID
    ap_gaji_account_id: uuid.UUID


class ApproveResponse(BaseModel):
    period_id: uuid.UUID
    status: str
    journal_entry_id: uuid.UUID


class DisburseRequest(BaseModel):
    payroll_period_id: uuid.UUID
    kas_bank_account_id: uuid.UUID


class DisburseResponse(BaseModel):
    period_id: uuid.UUID
    journal_entry_id: uuid.UUID
    total_net: str
