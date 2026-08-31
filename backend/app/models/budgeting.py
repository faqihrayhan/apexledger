"""Budgeting & Analytics ORM models (Module 8)."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BudgetStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"))
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fiscal_years.id")
    )
    budget_name: Mapped[str] = mapped_column(String(150))
    status: Mapped[BudgetStatusEnum] = mapped_column(
        Enum(BudgetStatusEnum, name="budget_status_enum"),
        default=BudgetStatusEnum.DRAFT,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profiles.id")
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_profiles.id")
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class BudgetLine(Base):
    __tablename__ = "budget_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budgets.id")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chart_of_accounts.id")
    )
    department_code: Mapped[str | None] = mapped_column(String(30))
    period_month: Mapped[int] = mapped_column(SmallInteger)
    budgeted_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class BudgetRevision(Base):
    __tablename__ = "budget_revisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budgets.id")
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    revised_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profiles.id")
    )
    revised_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    reason: Mapped[str] = mapped_column(Text)
    before_snapshot: Mapped[dict] = mapped_column(JSONB)
    created_at_col: Mapped[datetime] = mapped_column(
        "created_at", DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class EmployeeProductivityMetric(Base):
    __tablename__ = "employee_productivity_metrics"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id")
    )
    period_year: Mapped[int] = mapped_column(SmallInteger)
    period_month: Mapped[int] = mapped_column(SmallInteger)
    metric_code: Mapped[str] = mapped_column(String(40))
    metric_value: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
