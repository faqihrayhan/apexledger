"""
Pydantic schemas for General Ledger journal endpoints (Module 1).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class JournalLineIn(BaseModel):
    """One debit or credit line of a journal entry."""

    account_id: UUID
    debit_amount: Decimal = Field(default=Decimal("0"), ge=0)
    credit_amount: Decimal = Field(default=Decimal("0"), ge=0)
    department_code: str | None = None
    description: str | None = None


class JournalCreateRequest(BaseModel):
    """Payload for POST /gl/journals (calls fn_create_journal_entry)."""

    journal_date: date
    description: str | None = None
    currency_code: str = Field(default="IDR", min_length=3, max_length=3)
    lines: list[JournalLineIn] = Field(..., min_length=1)


class JournalCreateResponse(BaseModel):
    """Result of a successful journal creation (DRAFT status)."""

    journal_entry_id: UUID
    journal_number: str
    status: str = "DRAFT"


class JournalPostResponse(BaseModel):
    """Result of posting a journal entry (DRAFT -> POSTED)."""

    journal_entry_id: UUID
    status: str
    debit_total: Decimal
    credit_total: Decimal


class JournalReverseRequest(BaseModel):
    """Payload for reversing a POSTED entry."""

    reversal_date: date
    reason: str | None = None


class JournalReverseResponse(BaseModel):
    """Result of a reversal."""

    original_entry_id: UUID
    original_status: str
    reversal_entry_id: UUID
    reversal_number: str


class JournalSummary(BaseModel):
    """List item for GET /gl/journals."""

    id: UUID
    journal_number: str
    journal_date: date
    description: str | None
    status: str
    is_reversal: bool
    currency_code: str
    total_amount: Decimal
    line_count: int
