"""
System-level routes: first-boot setup wizard and instance status.

The setup wizard is the single entry point for a fresh ApexLedger
install (PRD: "First Boot (Wizard)"). It atomically creates:
1. The first ``entity`` (company / personal bookkeeping entity)
2. The ``SUPER_ADMIN`` user (local auth, Argon2-hashed password)
3. The current ``fiscal_year`` with its 12 monthly ``fiscal_periods``
4. An immutable ``system_logs`` audit entry

It refuses to run twice — once an entity exists, the only way to add
more is via authenticated admin endpoints (multi-entity comes later).
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.core.updates import check_for_updates
from app.db.session import get_db
from app.models.gl import FiscalPeriod, FiscalYear
from app.models.layer0 import Entity, RoleEnum, SystemLog, UserProfile
from app.schemas.system import (
    LicenseStatusResponse,
    SetupRequest,
    SetupResponse,
    SetupStatusResponse,
    UpdateStatusResponse,
)

router = APIRouter(prefix="/system", tags=["System"])


@router.get("/status", response_model=SetupStatusResponse)
async def get_setup_status(db: AsyncSession = Depends(get_db)) -> SetupStatusResponse:
    """Report whether this instance has completed first-boot setup."""
    result = await db.execute(select(func.count()).select_from(Entity))
    entity_count = result.scalar_one()
    return SetupStatusResponse(is_initialized=entity_count > 0)


@router.get("/updates", response_model=UpdateStatusResponse)
async def get_update_status() -> UpdateStatusResponse:
    """Opt-in update check (non-intrusive; privacy-first).

    Reports whether a newer release exists. Never downloads or
    installs anything — the user decides.
    """
    info = await check_for_updates()
    if info is None:
        return UpdateStatusResponse(
            update_available=False,
            current_version=None,
            latest_version=None,
            release_url=None,
        )
    return UpdateStatusResponse(
        update_available=info.is_update_available,
        current_version=info.current_version,
        latest_version=info.latest_version,
        release_url=info.release_url,
    )


@router.get("/license", response_model=LicenseStatusResponse)
async def get_license_status() -> LicenseStatusResponse:
    """License snapshot (cached; never blocks on the network).

    Community Edition reports itself without any phone-home. Enterprise
    keys fall back to the cached validation inside the grace window.
    """
    from app.core.license import license_status

    info = license_status()
    return LicenseStatusResponse(
        edition=info.edition,
        valid=info.valid,
        message=info.message,
        grace=info.grace,
    )


@router.post("/setup", response_model=SetupResponse, status_code=status.HTTP_201_CREATED)
async def run_setup(payload: SetupRequest, db: AsyncSession = Depends(get_db)):
    """First-boot setup wizard — creates entity, admin, and fiscal calendar."""
    # Guard: refuse to run if any entity already exists (wizard is once-only).
    result = await db.execute(select(func.count()).select_from(Entity))
    if result.scalar_one() > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This instance is already initialized. Setup can only run once.",
        )

    # Guard: base currency must exist in the seeded currencies table.
    from app.models.gl import Currency  # local import to avoid circulars

    currency_exists = await db.execute(
        select(func.count()).select_from(Currency).where(
            Currency.code == payload.base_currency_code
        )
    )
    if currency_exists.scalar_one() == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown currency code: {payload.base_currency_code}.",
        )

    # 1. Create the entity.
    entity = Entity(
        code=payload.entity_code,
        name=payload.entity_name,
        base_currency_code=payload.base_currency_code,
    )
    db.add(entity)
    await db.flush()  # assign entity.id without committing yet

    # 2. Create the SUPER_ADMIN user.
    admin = UserProfile(
        entity_id=entity.id,
        email=payload.admin_email,
        full_name=payload.admin_full_name,
        hashed_password=hash_password(payload.admin_password),
        role=RoleEnum.SUPER_ADMIN,
        force_password_reset=False,
    )
    db.add(admin)
    await db.flush()

    # 3. Create the fiscal year with 12 monthly periods.
    fiscal_year = FiscalYear(
        entity_id=entity.id,
        year_label=f"FY{payload.fiscal_year}",
        start_date=date(payload.fiscal_year, 1, 1),
        end_date=date(payload.fiscal_year, 12, 31),
    )
    db.add(fiscal_year)
    await db.flush()

    for month in range(1, 13):
        start = date(payload.fiscal_year, month, 1)
        end = date(
            payload.fiscal_year, month, monthrange(payload.fiscal_year, month)[1]
        )
        db.add(
            FiscalPeriod(
                fiscal_year_id=fiscal_year.id,
                period_number=month,
                start_date=start,
                end_date=end,
            )
        )

    # 4. Immutable audit trail entry.
    db.add(
        SystemLog(
            actor_id=admin.id,
            entity_id=entity.id,
            action="SETUP",
            table_name="entities",
            record_id=str(entity.id),
            after_data={
                "entity_code": entity.code,
                "fiscal_year": fiscal_year.year_label,
                "admin_email": admin.email,
            },
        )
    )

    await db.commit()

    token = create_access_token(
        user_id=admin.id,
        entity_id=entity.id,
        role=RoleEnum.SUPER_ADMIN.value,
    )

    return SetupResponse(
        entity_id=entity.id,
        entity_code=entity.code,
        user_id=admin.id,
        fiscal_year_id=fiscal_year.id,
        periods_created=12,
        access_token=token,
    )
