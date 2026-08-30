"""
Pydantic schemas for Chart of Accounts endpoints (Module 1).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class AccountCreate(BaseModel):
    """Payload for POST /gl/accounts."""

    account_code: str = Field(min_length=1, max_length=20)
    account_name: str = Field(min_length=1, max_length=150)
    account_type: str = Field(pattern="^(ASSET|LIABILITY|EQUITY|REVENUE|EXPENSE)$")
    normal_balance: str = Field(pattern="^(DEBIT|CREDIT)$")
    parent_account_id: UUID | None = None
    level: int = Field(default=1, ge=1, le=9)
    is_postable: bool = True
    is_active: bool = True


class AccountUpdate(BaseModel):
    """Payload for PATCH /gl/accounts/{id} — partial updates only.

    ``account_code`` and ``account_type`` are immutable after creation
    because journal lines already reference them.
    """

    account_name: str | None = Field(default=None, min_length=1, max_length=150)
    parent_account_id: UUID | None = None
    level: int | None = Field(default=None, ge=1, le=9)
    is_postable: bool | None = None
    is_active: bool | None = None


class AccountOut(BaseModel):
    """Full account representation."""

    id: UUID
    entity_id: UUID
    account_code: str
    account_name: str
    account_type: str
    normal_balance: str
    parent_account_id: UUID | None
    level: int
    is_postable: bool
    is_active: bool


class TrialBalanceRow(BaseModel):
    """One row of the trial balance report."""

    account_id: UUID
    account_code: str
    account_name: str
    account_type: str
    normal_balance: str
    total_debit: str
    total_credit: str
    net_debit: str
    net_credit: str


class TrialBalanceReport(BaseModel):
    """Trial balance with the double-entry proof totals."""

    as_of_date: str
    entity_id: UUID
    rows: list[TrialBalanceRow]
    grand_total_debit: str
    grand_total_credit: str
    is_balanced: bool
