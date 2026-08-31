"""
Fixed Asset Management Pydantic schemas (Module 7).

Amounts are strings in JSON (Decimal precision).
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field


class RegisterAssetRequest(BaseModel):
    asset_name: str = Field(min_length=1, max_length=150)
    asset_category: str
    acquisition_date: date
    acquisition_cost: str
    salvage_value: str = "0"
    useful_life_months: int = Field(gt=0)
    depreciation_method: str = "STRAIGHT_LINE"
    declining_rate_pct: str | None = None
    gl_asset_account_id: uuid.UUID
    gl_accum_depr_account_id: uuid.UUID
    funding_account_id: uuid.UUID


class RegisterAssetResponse(BaseModel):
    asset_id: uuid.UUID
    asset_code: str
    journal_entry_id: str


class AssetListOut(BaseModel):
    id: uuid.UUID
    asset_code: str
    asset_name: str
    asset_category: str
    acquisition_date: date
    acquisition_cost: str
    salvage_value: str
    accumulated_depreciation: str
    book_value: str
    status: str


class DepreciationBatchRequest(BaseModel):
    period_year: int = Field(ge=2000, le=2100)
    period_month: int = Field(ge=1, le=12)


class DepreciationBatchResponse(BaseModel):
    asset_count: int
    total_depreciation: str
    journal_entry_id: str | None = None
    note: str | None = None


class DepreciationScheduleOut(BaseModel):
    period_year: int
    period_month: int
    depreciation_amount: str
    accumulated_after: str
    book_value_after: str
    journal_entry_id: uuid.UUID | None = None


class DisposeAssetRequest(BaseModel):
    disposal_date: date
    disposal_type: str
    disposal_proceeds: str = "0"
    proceeds_account_id: uuid.UUID
    gain_loss_account_id: uuid.UUID


class DisposeAssetResponse(BaseModel):
    disposal_id: uuid.UUID
    gain_loss: str
    journal_entry_id: str
