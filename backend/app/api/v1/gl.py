"""
General Ledger API routes (Module 1 — Gate 2.2).

Thin wrappers around the PL/pgSQL RPCs. All business rules live in the
database; this layer only:
1. Validates payloads (Pydantic),
2. Provides the RLS-scoped session (JWT claims injected),
3. Calls the RPC,
4. Maps RPC errors to clean HTTP responses.

Dual-layer defense (PRD Layer 0.4): the DB enforces RLS + RPC guards,
and read endpoints additionally filter by the caller's entity explicitly
(required while the service connects as a superuser, which bypasses RLS).
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_with_rls
from app.core.rpc_errors import raise_from_rpc
from app.core.security import get_current_user
from app.models.gl import JournalEntry, JournalLine
from app.schemas.gl import (
    JournalCreateRequest,
    JournalCreateResponse,
    JournalPostResponse,
    JournalReverseRequest,
    JournalReverseResponse,
    JournalSummary,
)

router = APIRouter(prefix="/gl", tags=["General Ledger"])


def _parse_rpc_json(raw: object) -> dict:
    """Decode an RPC JSONB result.

    asyncpg may return JSONB as a JSON *string* (default codec) or as an
    already-decoded object depending on driver/dialect version — handle both.
    """
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)  # type: ignore[arg-type]


@router.post("/journals", response_model=JournalCreateResponse, status_code=201)
async def create_journal(
    payload: JournalCreateRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> JournalCreateResponse:
    """Create a DRAFT journal entry via fn_create_journal_entry."""
    # Serialize lines exactly as the RPC expects (JSONB array of objects).
    lines_json = json.dumps(
        [
            {
                "account_id": str(line.account_id),
                "debit_amount": str(line.debit_amount),
                "credit_amount": str(line.credit_amount),
                "department_code": line.department_code,
                "description": line.description,
            }
            for line in payload.lines
        ]
    )

    try:
        result = await db.execute(
            text(
                "SELECT fn_create_journal_entry("
                "  CAST(:entity_id AS uuid), CAST(:jdate AS date),"
                "  :descr, :ccy, CAST(:lines AS jsonb)"
                ") AS rpc"
            ),
            {
                "entity_id": current_user["entity_id"],
                "jdate": payload.journal_date,
                "descr": payload.description,
                "ccy": payload.currency_code,
                "lines": lines_json,
            },
        )
        rpc_result = _parse_rpc_json(result.scalar_one())

        return JournalCreateResponse(
            journal_entry_id=rpc_result["journal_entry_id"],
            journal_number=rpc_result["journal_number"],
        )

    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.get("/journals", response_model=list[JournalSummary])
async def list_journals(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, le=200),
) -> list[JournalSummary]:
    """List journal entries for the current entity.

    Application-level entity filter (dual-layer defense): every caller is
    scoped to their own entity even if RLS is bypassed by the connection
    role (SUPER_ADMIN is an admin *of their entity*, not a global admin).
    """
    stmt = (
        select(
            JournalEntry.id,
            JournalEntry.journal_number,
            JournalEntry.journal_date,
            JournalEntry.description,
            JournalEntry.status,
            JournalEntry.is_reversal,
            JournalEntry.currency_code,
            func.coalesce(func.sum(JournalLine.debit_amount), 0).label("total_amount"),
            func.count(JournalLine.id).label("line_count"),
        )
        .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id, isouter=True)
        .where(JournalEntry.entity_id == uuid.UUID(current_user["entity_id"]))
        .group_by(JournalEntry.id)
        .order_by(JournalEntry.journal_date.desc(), JournalEntry.created_at.desc())
        .limit(limit)
    )

    if status_filter:
        stmt = stmt.where(JournalEntry.status == status_filter)

    result = await db.execute(stmt)
    rows = result.all()

    return [
        JournalSummary(
            id=row.id,
            journal_number=row.journal_number,
            journal_date=row.journal_date,
            description=row.description,
            status=row.status,
            is_reversal=row.is_reversal,
            currency_code=row.currency_code,
            total_amount=row.total_amount,
            line_count=row.line_count,
        )
        for row in rows
    ]


@router.post("/journals/{journal_id}/post", response_model=JournalPostResponse)
async def post_journal(
    journal_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
) -> JournalPostResponse:
    """Post a DRAFT entry via fn_post_journal_entry (DRAFT -> POSTED)."""
    try:
        result = await db.execute(
            text("SELECT fn_post_journal_entry(CAST(:je_id AS uuid)) AS rpc"),
            {"je_id": journal_id},
        )
        rpc_result = _parse_rpc_json(result.scalar_one())

        return JournalPostResponse(
            journal_entry_id=rpc_result["journal_entry_id"],
            status=rpc_result["status"],
            debit_total=rpc_result["debit_total"],
            credit_total=rpc_result["credit_total"],
        )

    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.post("/journals/{journal_id}/reverse", response_model=JournalReverseResponse)
async def reverse_journal(
    journal_id: str,
    payload: JournalReverseRequest,
    db: AsyncSession = Depends(get_db_with_rls),
) -> JournalReverseResponse:
    """Reverse a POSTED entry via fn_reverse_journal_entry."""
    try:
        result = await db.execute(
            text(
                "SELECT fn_reverse_journal_entry("
                "  CAST(:je_id AS uuid), CAST(:rdate AS date), :reason"
                ") AS rpc"
            ),
            {"je_id": journal_id, "rdate": payload.reversal_date, "reason": payload.reason},
        )
        rpc_result = _parse_rpc_json(result.scalar_one())

        return JournalReverseResponse(
            original_entry_id=rpc_result["original_entry_id"],
            original_status=rpc_result["original_status"],
            reversal_entry_id=rpc_result["reversal_entry_id"],
            reversal_number=rpc_result["reversal_number"],
        )

    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.get("/health")
async def gl_health():
    """Simple health-check endpoint for the GL module."""
    return {"module": "general_ledger", "status": "ok"}
