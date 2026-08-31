"""
Fixed Asset Management API routes (Module 7).

RPC wrappers for asset registration (auto-post acquisition),
monthly depreciation batch (aggregated single JE), disposal
with gain/loss posting, and read-only schedule listing.

Business rules live in the PL/pgSQL RPCs; this layer enforces
authentication, coarse role guards, and entity scoping via RLS.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_with_rls
from app.api.v1.sales import _parse_rpc_json, _require_roles
from app.core.rpc_errors import raise_from_rpc
from app.core.security import get_current_user
from app.schemas.fixed_asset import (
    AssetListOut,
    DepreciationBatchRequest,
    DepreciationBatchResponse,
    DepreciationScheduleOut,
    DisposeAssetRequest,
    DisposeAssetResponse,
    RegisterAssetRequest,
    RegisterAssetResponse,
)

router = APIRouter(prefix="/assets", tags=["Fixed Assets"])

FINANCE_ROLES = {"FINANCE_OPERATOR", "DEPT_HEAD_FA", "SUPER_ADMIN"}
DISPOSE_ROLES = {"DEPT_HEAD_FA", "SUPER_ADMIN"}


def _amt(v: object) -> str:
    """Serialize a Decimal amount without scientific notation."""
    from decimal import Decimal

    if isinstance(v, Decimal):
        return format(v, "f")
    return str(v)


@router.post("", response_model=RegisterAssetResponse)
async def register_asset(
    payload: RegisterAssetRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> RegisterAssetResponse:
    """Register an asset and auto-post the acquisition JE."""
    _require_roles(current_user, FINANCE_ROLES)

    try:
        result = await db.execute(
            text(
                "SELECT fn_register_fixed_asset("
                "CAST(:entity_id AS uuid), :asset_name, "
                "CAST(:asset_category AS asset_category_enum), "
                "CAST(:acquisition_date AS date), "
                "CAST(:acquisition_cost AS numeric), "
                "CAST(:salvage_value AS numeric), "
                "CAST(:useful_life_months AS smallint), "
                "CAST(:depreciation_method "
                "  AS depreciation_method_enum), "
                "CAST(:declining_rate_pct AS numeric), "
                "CAST(:gl_asset_account_id AS uuid), "
                "CAST(:gl_accum_depr_account_id AS uuid), "
                "CAST(:funding_account_id AS uuid))"
            ),
            {
                "entity_id": current_user["entity_id"],
                "asset_name": payload.asset_name,
                "asset_category": payload.asset_category,
                "acquisition_date": payload.acquisition_date,
                "acquisition_cost": payload.acquisition_cost,
                "salvage_value": payload.salvage_value,
                "useful_life_months": payload.useful_life_months,
                "depreciation_method": payload.depreciation_method,
                "declining_rate_pct": payload.declining_rate_pct,
                "gl_asset_account_id": payload.gl_asset_account_id,
                "gl_accum_depr_account_id": (
                    payload.gl_accum_depr_account_id
                ),
                "funding_account_id": payload.funding_account_id,
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        raise raise_from_rpc(exc) from exc

    return RegisterAssetResponse(
        asset_id=rpc["asset_id"],
        asset_code=rpc["asset_code"],
        journal_entry_id=rpc["journal_entry_id"],
    )


@router.get("", response_model=list[AssetListOut])
async def list_assets(
    status: str | None = None,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[AssetListOut]:
    """List assets for the current entity (dual-layer scoped)."""
    if status:
        rows = await db.execute(
            text(
                "SELECT id, asset_code, asset_name, "
                "asset_category, acquisition_date, "
                "acquisition_cost, salvage_value, "
                "accumulated_depreciation, book_value, "
                "status FROM fixed_assets "
                "WHERE entity_id = CAST(:entity_id AS uuid) "
                "AND status = CAST(:status AS asset_status_enum) "
                "ORDER BY created_at"
            ),
            {
                "entity_id": current_user["entity_id"],
                "status": status,
            },
        )
    else:
        rows = await db.execute(
            text(
                "SELECT id, asset_code, asset_name, "
                "asset_category, acquisition_date, "
                "acquisition_cost, salvage_value, "
                "accumulated_depreciation, book_value, "
                "status FROM fixed_assets "
                "WHERE entity_id = CAST(:entity_id AS uuid) "
                "ORDER BY created_at"
            ),
            {"entity_id": current_user["entity_id"]},
        )
    return [
        AssetListOut(
            id=r[0],
            asset_code=r[1],
            asset_name=r[2],
            asset_category=r[3],
            acquisition_date=r[4],
            acquisition_cost=_amt(r[5]),
            salvage_value=_amt(r[6]),
            accumulated_depreciation=_amt(r[7]),
            book_value=_amt(r[8]),
            status=r[9],
        )
        for r in rows.fetchall()
    ]


@router.post(
    "/depreciation/batch",
    response_model=DepreciationBatchResponse,
)
async def run_depreciation_batch(
    payload: DepreciationBatchRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> DepreciationBatchResponse:
    """Run the monthly depreciation batch for the entity."""
    _require_roles(current_user, FINANCE_ROLES)

    try:
        result = await db.execute(
            text(
                "SELECT fn_run_monthly_depreciation_batch("
                "CAST(:entity_id AS uuid), "
                "CAST(:period_year AS smallint), "
                "CAST(:period_month AS smallint))"
            ),
            {
                "entity_id": current_user["entity_id"],
                "period_year": payload.period_year,
                "period_month": payload.period_month,
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        raise raise_from_rpc(exc) from exc

    return DepreciationBatchResponse(
        asset_count=rpc["asset_count"],
        total_depreciation=_amt(rpc["total_depreciation"]),
        journal_entry_id=rpc.get("journal_entry_id"),
        note=rpc.get("note"),
    )


@router.get(
    "/{asset_id}/schedule",
    response_model=list[DepreciationScheduleOut],
)
async def get_asset_schedule(
    asset_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[DepreciationScheduleOut]:
    """Read-only depreciation schedule for one asset."""
    rows = await db.execute(
        text(
            "SELECT ads.period_year, ads.period_month, "
            "ads.depreciation_amount, ads.accumulated_after, "
            "ads.book_value_after, ads.journal_entry_id "
            "FROM asset_depreciation_schedule ads "
            "JOIN fixed_assets fa ON fa.id = ads.asset_id "
            "WHERE fa.entity_id = CAST(:entity_id AS uuid) "
            "AND ads.asset_id = CAST(:asset_id AS uuid) "
            "ORDER BY ads.period_year, ads.period_month"
        ),
        {
            "entity_id": current_user["entity_id"],
            "asset_id": asset_id,
        },
    )
    return [
        DepreciationScheduleOut(
            period_year=r[0],
            period_month=r[1],
            depreciation_amount=_amt(r[2]),
            accumulated_after=_amt(r[3]),
            book_value_after=_amt(r[4]),
            journal_entry_id=r[5],
        )
        for r in rows.fetchall()
    ]


@router.post(
    "/{asset_id}/dispose",
    response_model=DisposeAssetResponse,
)
async def dispose_asset(
    asset_id: str,
    payload: DisposeAssetRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> DisposeAssetResponse:
    """Dispose an asset: write-off/sale/donation + gain/loss GL."""
    _require_roles(current_user, DISPOSE_ROLES)

    try:
        result = await db.execute(
            text(
                "SELECT fn_dispose_fixed_asset("
                "CAST(:asset_id AS uuid), "
                "CAST(:disposal_date AS date), "
                "CAST(:disposal_type AS disposal_type_enum), "
                "CAST(:disposal_proceeds AS numeric), "
                "CAST(:proceeds_account_id AS uuid), "
                "CAST(:gain_loss_account_id AS uuid))"
            ),
            {
                "asset_id": asset_id,
                "disposal_date": payload.disposal_date,
                "disposal_type": payload.disposal_type,
                "disposal_proceeds": payload.disposal_proceeds,
                "proceeds_account_id": payload.proceeds_account_id,
                "gain_loss_account_id": payload.gain_loss_account_id,
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        raise raise_from_rpc(exc) from exc

    return DisposeAssetResponse(
        disposal_id=rpc["disposal_id"],
        gain_loss=_amt(rpc["gain_loss"]),
        journal_entry_id=rpc["journal_entry_id"],
    )
