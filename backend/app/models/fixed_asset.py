"""Fixed Asset Management ORM models (Module 7)."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AssetCategoryEnum(enum.StrEnum):
    TANGIBLE = "TANGIBLE"
    INTANGIBLE = "INTANGIBLE"


class DepreciationMethodEnum(enum.StrEnum):
    STRAIGHT_LINE = "STRAIGHT_LINE"
    DECLINING_BALANCE = "DECLINING_BALANCE"


class AssetStatusEnum(enum.StrEnum):
    ACTIVE = "ACTIVE"
    FULLY_DEPRECIATED = "FULLY_DEPRECIATED"
    DISPOSED = "DISPOSED"


class DisposalTypeEnum(enum.StrEnum):
    SALE = "SALE"
    WRITE_OFF = "WRITE_OFF"
    DONATION = "DONATION"


class FixedAsset(Base):
    __tablename__ = "fixed_assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"))
    asset_code: Mapped[str] = mapped_column(String(30), unique=True)
    asset_name: Mapped[str] = mapped_column(String(150))
    asset_category: Mapped[AssetCategoryEnum] = mapped_column(
        Enum(AssetCategoryEnum, name="asset_category_enum")
    )
    department_code: Mapped[str | None] = mapped_column(String(30))
    acquisition_date: Mapped[date] = mapped_column(Date)
    acquisition_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 2)
    )
    salvage_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0")
    )
    useful_life_months: Mapped[int] = mapped_column(SmallInteger)
    depreciation_method: Mapped[DepreciationMethodEnum] = mapped_column(
        Enum(DepreciationMethodEnum, name="depreciation_method_enum"),
        default=DepreciationMethodEnum.STRAIGHT_LINE,
    )
    declining_rate_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4)
    )
    accumulated_depreciation: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0")
    )
    book_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[AssetStatusEnum] = mapped_column(
        Enum(AssetStatusEnum, name="asset_status_enum"),
        default=AssetStatusEnum.ACTIVE,
    )
    gl_asset_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chart_of_accounts.id")
    )
    gl_accum_depr_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chart_of_accounts.id")
    )
    gl_depr_expense_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chart_of_accounts.id")
    )
    acquisition_journal_entry_id: Mapped[uuid.UUID | None] = (
        mapped_column(ForeignKey("journal_entries.id"))
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class AssetDepreciationSchedule(Base):
    __tablename__ = "asset_depreciation_schedule"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fixed_assets.id")
    )
    period_year: Mapped[int] = mapped_column(SmallInteger)
    period_month: Mapped[int] = mapped_column(SmallInteger)
    depreciation_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2)
    )
    accumulated_after: Mapped[Decimal] = mapped_column(
        Numeric(18, 2)
    )
    book_value_after: Mapped[Decimal] = mapped_column(
        Numeric(18, 2)
    )
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class AssetDisposal(Base):
    __tablename__ = "asset_disposals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fixed_assets.id")
    )
    disposal_date: Mapped[date] = mapped_column(Date)
    disposal_type: Mapped[DisposalTypeEnum] = mapped_column(
        Enum(DisposalTypeEnum, name="disposal_type_enum")
    )
    disposal_proceeds: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0")
    )
    book_value_at_disposal: Mapped[Decimal] = mapped_column(
        Numeric(18, 2)
    )
    gain_loss_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2)
    )
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_profiles.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
