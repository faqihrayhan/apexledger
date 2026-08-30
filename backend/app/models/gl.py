"""
Module 1 — General Ledger ORM models.

Covers: currencies, exchange rates, chart of accounts, fiscal years/periods,
journal entries, and journal lines.  These form the core double-entry
accounting engine that every other module posts into.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AccountTypeEnum(enum.StrEnum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class NormalBalanceEnum(enum.StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class JournalStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class FiscalPeriodStatusEnum(enum.StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LOCKED = "LOCKED"


# ---------------------------------------------------------------------------
# Currency & Exchange Rates
# ---------------------------------------------------------------------------


class Currency(Base):
    """ISO 4217 currency definition."""

    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(5), nullable=False)
    decimal_places: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)


class ExchangeRate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Daily exchange rate between two currencies."""

    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("from_currency", "to_currency", "effective_date"),
        CheckConstraint("rate > 0", name="chk_positive_rate"),
    )

    from_currency: Mapped[str] = mapped_column(
        String(3), ForeignKey("currencies.code"), nullable=False
    )
    to_currency: Mapped[str] = mapped_column(
        String(3), ForeignKey("currencies.code"), nullable=False
    )
    rate: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)


# ---------------------------------------------------------------------------
# Chart of Accounts
# ---------------------------------------------------------------------------


class ChartOfAccounts(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Account in the entity's chart of accounts.

    Supports hierarchical account groups via ``parent_account_id``.
    Only accounts with ``is_postable=True`` accept journal line postings.
    """

    __tablename__ = "chart_of_accounts"
    __table_args__ = (UniqueConstraint("entity_id", "account_code"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    parent_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id"), nullable=True
    )
    account_code: Mapped[str] = mapped_column(String(20), nullable=False)
    account_name: Mapped[str] = mapped_column(String(150), nullable=False)
    account_type: Mapped[AccountTypeEnum] = mapped_column(
        Enum(AccountTypeEnum, name="account_type_enum", create_type=True), nullable=False
    )
    normal_balance: Mapped[NormalBalanceEnum] = mapped_column(
        Enum(NormalBalanceEnum, name="normal_balance_enum", create_type=True), nullable=False
    )
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    is_postable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ---------------------------------------------------------------------------
# Fiscal Years & Periods
# ---------------------------------------------------------------------------


class FiscalYear(UUIDPrimaryKeyMixin, Base):
    """Fiscal year container (e.g. FY2026)."""

    __tablename__ = "fiscal_years"
    __table_args__ = (UniqueConstraint("entity_id", "year_label"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    year_label: Mapped[str] = mapped_column(String(9), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="OPEN")

    # Relationships
    periods: Mapped[list[FiscalPeriod]] = relationship(back_populates="fiscal_year")


class FiscalPeriod(UUIDPrimaryKeyMixin, Base):
    """Monthly fiscal period within a fiscal year."""

    __tablename__ = "fiscal_periods"
    __table_args__ = (
        UniqueConstraint("fiscal_year_id", "period_number"),
        CheckConstraint("period_number BETWEEN 1 AND 12", name="chk_period_range"),
    )

    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fiscal_years.id"), nullable=False
    )
    period_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="OPEN")

    # Relationships
    fiscal_year: Mapped[FiscalYear] = relationship(back_populates="periods")


# ---------------------------------------------------------------------------
# Journal Entries & Lines
# ---------------------------------------------------------------------------


class JournalEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Double-entry journal header.

    Immutable ledger principle: once posted, entries cannot be edited —
    corrections are made via reversing entries.  ``UPDATE`` and ``DELETE``
    on this table are revoked at the DB level.
    """

    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("entity_id", "journal_number"),
        Index("idx_journal_entries_period", "fiscal_period_id", "status"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    journal_number: Mapped[str] = mapped_column(String(30), nullable=False)
    journal_date: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fiscal_periods.id"), nullable=False
    )
    source_module: Mapped[str] = mapped_column(String(30), nullable=False, default="GL_MANUAL")
    source_reference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency_code: Mapped[str] = mapped_column(
        String(3), ForeignKey("currencies.code"), nullable=False
    )
    exchange_rate: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="DRAFT")
    is_reversal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reversed_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    posted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    lines: Mapped[list[JournalLine]] = relationship(
        back_populates="journal_entry", cascade="all, delete-orphan"
    )


class JournalLine(UUIDPrimaryKeyMixin, Base):
    """Individual debit or credit line within a journal entry.

    Enforces the single-side constraint: each line is either a debit
    or a credit, never both.
    """

    __tablename__ = "journal_lines"
    __table_args__ = (
        UniqueConstraint("journal_entry_id", "line_number"),
        CheckConstraint(
            "(debit_amount > 0 AND credit_amount = 0) OR "
            "(credit_amount > 0 AND debit_amount = 0)",
            name="chk_single_side",
        ),
        Index("idx_journal_lines_account", "account_id"),
    )

    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id"), nullable=False
    )
    debit_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    credit_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    base_currency_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    department_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    cost_center_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    journal_entry: Mapped[JournalEntry] = relationship(back_populates="lines")
