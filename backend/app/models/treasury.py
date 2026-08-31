"""
Module 6 — Treasury & Cash Management ORM models.

Covers: bank accounts, petty cash funds, kasbon requests,
kasbon settlements + lines, bank statement lines,
cash flow forecast lines.

All mutations flow through the PL/pgSQL RPCs; ORM models serve
typed reads and app-level entity filtering (dual-layer defense).
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.layer0 import RoleEnum


class KasbonStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISBURSED = "DISBURSED"
    SETTLED = "SETTLED"


class SettlementStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class BankAccount(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "bank_accounts"
    __table_args__ = (
        UniqueConstraint("entity_id", "account_number"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    bank_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    account_number: Mapped[str] = mapped_column(
        String(30), nullable=False
    )
    account_name: Mapped[str] = mapped_column(
        String(150), nullable=False
    )
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, default="IDR"
    )
    gl_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )


class KasbonRequest(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "kasbon_requests"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"),
        nullable=False,
    )
    department_code: Mapped[str | None] = mapped_column(String(30))
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    request_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[KasbonStatusEnum] = mapped_column(
        Enum(KasbonStatusEnum, name="kasbon_status_enum"),
        nullable=False,
        default=KasbonStatusEnum.DRAFT,
    )
    required_approval_role: Mapped[RoleEnum | None] = mapped_column(
        Enum(RoleEnum, name="role_enum")
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id")
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    disbursed_journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id")
    )
    disbursed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class KasbonSettlement(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "kasbon_settlements"

    kasbon_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kasbon_requests.id"),
        nullable=False,
    )
    settlement_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_amount_used: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    refund_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    additional_claim_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    status: Mapped[SettlementStatusEnum] = mapped_column(
        Enum(SettlementStatusEnum, name="settlement_status_enum"),
        nullable=False,
        default=SettlementStatusEnum.DRAFT,
    )
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id")
    )


class KasbonSettlementLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "kasbon_settlement_lines"

    kasbon_settlement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kasbon_settlements(id)", ondelete="CASCADE"),
        nullable=False,
    )
    expense_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        String(200), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    receipt_reference: Mapped[str | None] = mapped_column(String(50))


class BankStatementLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "bank_statement_lines"

    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bank_accounts.id"),
        nullable=False,
    )
    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    is_matched: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    matched_transaction_type: Mapped[str | None] = mapped_column(
        String(30)
    )
    matched_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True)
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(UTC),
    )
