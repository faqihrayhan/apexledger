"""
Chart of Accounts & Trial Balance API routes (Module 1 — Gate 2.4/2.5).

CoA CRUD is thin (ORM + application-level entity filter); the Trial
Balance report is a thin wrapper around the ``fn_trial_balance`` RPC.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_with_rls
from app.core.rpc_errors import raise_from_rpc
from app.core.security import get_current_user
from app.models.gl import ChartOfAccounts, JournalEntry, JournalLine
from app.schemas.coa import (
    AccountCreate,
    AccountOut,
    AccountUpdate,
    TrialBalanceReport,
    TrialBalanceRow,
)

router = APIRouter(prefix="/gl", tags=["Chart of Accounts"])

FINANCE_ROLES = ("SUPER_ADMIN", "IT_ADMIN", "FINANCE_OPERATOR", "DEPT_HEAD_FA")


def _account_out(acc: ChartOfAccounts) -> AccountOut:
    """Build an AccountOut from an ORM account."""
    return AccountOut(
        id=acc.id,
        entity_id=acc.entity_id,
        account_code=acc.account_code,
        account_name=acc.account_name,
        account_type=acc.account_type.value,
        normal_balance=acc.normal_balance.value,
        parent_account_id=acc.parent_account_id,
        level=acc.level,
        is_postable=acc.is_postable,
        is_active=acc.is_active,
    )


def _forbid_non_finance() -> HTTPException:
    """403 builder for non-finance roles touching the CoA."""
    return HTTPException(
        status_code=403,
        detail={
            "error_code": "FORBIDDEN_ROLE",
            "message": "Only finance roles can manage accounts.",
        },
    )


async def _get_owned_account(
    db: AsyncSession, account_id: str, entity_id: str
) -> ChartOfAccounts:
    """Fetch an account, ensuring it belongs to the caller's entity."""
    try:
        account_uuid = uuid.UUID(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid account id.") from exc

    account = await db.get(ChartOfAccounts, account_uuid)
    if account is None or str(account.entity_id) != entity_id:
        raise HTTPException(status_code=404, detail="Account not found.")
    return account


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[AccountOut]:
    """List all accounts for the caller's entity (application-scoped)."""
    result = await db.execute(
        select(ChartOfAccounts)
        .where(ChartOfAccounts.entity_id == uuid.UUID(current_user["entity_id"]))
        .order_by(ChartOfAccounts.account_code)
    )
    return [_account_out(acc) for acc in result.scalars().all()]


@router.post("/accounts", response_model=AccountOut, status_code=201)
async def create_account(
    payload: AccountCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> AccountOut:
    """Create a new account in the caller's chart of accounts."""
    if current_user["role"] not in FINANCE_ROLES:
        raise _forbid_non_finance()

    account = ChartOfAccounts(
        entity_id=uuid.UUID(current_user["entity_id"]),
        account_code=payload.account_code,
        account_name=payload.account_name,
        account_type=payload.account_type,
        normal_balance=payload.normal_balance,
        parent_account_id=payload.parent_account_id,
        level=payload.level,
        is_postable=payload.is_postable,
        is_active=payload.is_active,
    )
    db.add(account)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "ACCOUNT_DUPLICATE",
                "message": "An account with this code already exists for this entity.",
            },
        ) from exc

    await db.refresh(account)
    return _account_out(account)


@router.get("/accounts/{account_id}", response_model=AccountOut)
async def get_account(
    account_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> AccountOut:
    """Fetch one account by id (entity-scoped)."""
    account = await _get_owned_account(db, account_id, current_user["entity_id"])
    return _account_out(account)


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: str,
    payload: AccountUpdate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> AccountOut:
    """Partially update an account (name/parent/level/postable/active)."""
    if current_user["role"] not in FINANCE_ROLES:
        raise _forbid_non_finance()

    account = await _get_owned_account(db, account_id, current_user["entity_id"])

    # Explicit None-checks so falsy values (level=1, is_postable=False) work.
    if payload.account_name is not None:
        account.account_name = payload.account_name
    if payload.parent_account_id is not None:
        account.parent_account_id = payload.parent_account_id
    if payload.level is not None:
        account.level = payload.level
    if payload.is_postable is not None:
        account.is_postable = payload.is_postable
    if payload.is_active is not None:
        account.is_active = payload.is_active

    await db.commit()
    await db.refresh(account)
    return _account_out(account)


@router.delete("/accounts/{account_id}", status_code=204)
async def deactivate_account(
    account_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> None:
    """Soft-delete: deactivate an account instead of hard-deleting.

    Accounts with journal history are never removed — they are flagged
    ``is_active = false`` so they disappear from pickers but keep their
    ledger trail (PRD immutability principle).
    """
    if current_user["role"] not in FINANCE_ROLES:
        raise _forbid_non_finance()

    account = await _get_owned_account(db, account_id, current_user["entity_id"])

    # Guard: check whether the account has ANY journal lines (posted or not).
    has_postings = await db.execute(
        select(JournalLine.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(JournalLine.account_id == account.id)
        .limit(1)
    )
    if has_postings.first() is not None:
        # Soft-deactivate only — history must be preserved.
        account.is_active = False
        await db.commit()
        return

    # No history: safe to hard-delete (cleanup of a mistyped account).
    await db.delete(account)
    await db.commit()


# ---------------------------------------------------------------------------
# Trial Balance (Gate 2.5)
# ---------------------------------------------------------------------------


@router.get("/reports/trial-balance", response_model=TrialBalanceReport)
async def trial_balance(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
    as_of: date | None = Query(default=None),
) -> TrialBalanceReport:
    """Trial balance as of a date (defaults to today).

    The double-entry proof: grand_total_debit == grand_total_credit.
    """
    as_of_value = as_of or date.today()
    as_of_str = as_of_value.isoformat()

    try:
        result = await db.execute(
            text(
                "SELECT * FROM fn_trial_balance("
                "  CAST(:entity_id AS uuid), CAST(:as_of AS date)"
                ") ORDER BY account_code"
            ),
            {"entity_id": current_user["entity_id"], "as_of": as_of_value},
        )
        rows_raw = result.mappings().all()
    except Exception as exc:
        raise raise_from_rpc(exc) from exc

    rows = [
        TrialBalanceRow(
            account_id=r["account_id"],
            account_code=r["account_code"],
            account_name=r["account_name"],
            account_type=r["account_type"],
            normal_balance=r["normal_balance"],
            total_debit=str(r["total_debit"]),
            total_credit=str(r["total_credit"]),
            net_debit=str(r["net_debit"]),
            net_credit=str(r["net_credit"]),
        )
        for r in rows_raw
    ]

    grand_debit = sum((Decimal(r.net_debit) for r in rows), Decimal(0))
    grand_credit = sum((Decimal(r.net_credit) for r in rows), Decimal(0))

    return TrialBalanceReport(
        as_of_date=as_of_str,
        entity_id=uuid.UUID(current_user["entity_id"]),
        rows=rows,
        grand_total_debit=str(grand_debit),
        grand_total_credit=str(grand_credit),
        is_balanced=(grand_debit == grand_credit),
    )
