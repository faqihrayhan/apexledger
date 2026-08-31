"""
Module 2 — HR Finance, Payroll & Tax ORM models.

Covers: employees, company calendar, attendance, payroll component
master, BPJS rate config, PPh 21 TER table, PTKP mapping, overtime
multiplier, payroll periods/entries/lines.

All lifecycle mutations (calculate/approve/disburse) happen through
PL/pgSQL RPCs; these ORM models exist for typed reads and app-level
entity filtering (dual-layer defense).
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EmploymentTypeEnum(enum.StrEnum):
    MONTHLY = "MONTHLY"
    DAILY = "DAILY"


class PayrollPeriodStatusEnum(enum.StrEnum):
    DRAFT = "DRAFT"
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"


class ComponentTypeEnum(enum.StrEnum):
    EARNING = "EARNING"
    DEDUCTION = "DEDUCTION"


class PtkpStatusEnum(enum.StrEnum):
    TK0 = "TK0"
    TK1 = "TK1"
    TK2 = "TK2"
    TK3 = "TK3"
    K0 = "K0"
    K1 = "K1"
    K2 = "K2"
    K3 = "K3"


class Employee(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Employee master record (entity-scoped)."""

    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("entity_id", "employee_code"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    user_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=True
    )
    employee_code: Mapped[str] = mapped_column(String(20), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    position: Mapped[str | None] = mapped_column(String(100))
    department_code: Mapped[str | None] = mapped_column(String(30))
    employment_type: Mapped[str] = mapped_column(
        Enum(EmploymentTypeEnum, name="employment_type_enum"),
        nullable=False,
        default=EmploymentTypeEnum.MONTHLY,
    )
    base_salary: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    ptkp_status: Mapped[str] = mapped_column(
        Enum(PtkpStatusEnum, name="ptkp_status_enum"),
        nullable=False,
        default=PtkpStatusEnum.TK0,
    )
    bank_account_no: Mapped[str | None] = mapped_column(String(30))
    npwp: Mapped[str | None] = mapped_column(String(20))
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    termination_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CompanyCalendar(Base):
    """Working-day calendar per entity (basis for monthly working days)."""

    __tablename__ = "company_calendar"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), primary_key=True
    )
    calendar_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_working_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(String(100))


class AttendanceRecord(UUIDPrimaryKeyMixin, Base):
    """Daily attendance for one employee."""

    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("employee_id", "work_date"),)

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    late_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overtime_hours: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )


class PayrollComponentMaster(Base):
    """Earning/deduction component (config-driven, GL-linked)."""

    __tablename__ = "payroll_component_master"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(
        Enum(ComponentTypeEnum, name="component_type_enum"), nullable=False
    )
    is_taxable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    gl_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id"), nullable=True
    )


class PayrollPeriod(UUIDPrimaryKeyMixin, Base):
    """Monthly payroll run header with lifecycle status."""

    __tablename__ = "payroll_periods"
    __table_args__ = (
        UniqueConstraint("entity_id", "period_year", "period_month"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False
    )
    period_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    period_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(PayrollPeriodStatusEnum, name="payroll_period_status_enum"),
        nullable=False,
        default=PayrollPeriodStatusEnum.DRAFT,
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ap_gaji_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id")
    )
    accrual_journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id")
    )
    disbursed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id")
    )
    disbursed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class PayrollEntry(UUIDPrimaryKeyMixin, Base):
    """Calculated payroll for one employee in one period."""

    __tablename__ = "payroll_entries"
    __table_args__ = (UniqueConstraint("payroll_period_id", "employee_id"),)

    payroll_period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_periods.id"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    working_days: Mapped[int] = mapped_column(Integer, nullable=False)
    unpaid_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overtime_hours: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False, default=0
    )
    gross_earning: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    total_deduction: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0
    )
    net_pay: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class PayrollEntryLine(UUIDPrimaryKeyMixin, Base):
    """Component breakdown line for a payroll entry."""

    __tablename__ = "payroll_entry_lines"

    payroll_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payroll_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_code: Mapped[str] = mapped_column(
        String(30), ForeignKey("payroll_component_master.code"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(String(200))
