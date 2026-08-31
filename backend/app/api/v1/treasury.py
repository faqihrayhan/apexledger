"""
Treasury & Cash Management API routes (Module 6).

Kasbon lifecycle (submit -> approve -> disburse -> settle),
bank accounts, statement import + auto-match, and the
read-only cash flow forecast. Business rules live in the
PL/pgSQL RPCs; this layer enforces auth, coarse role guards,
and entity scoping via RLS.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_with_rls
from app.api.v1.sales import _parse_rpc_json, _require_roles
from app.core.rpc_errors import raise_from_rpc
from app.core.security import get_current_user
from app.models.treasury import BankAccount, BankStatementLine, KasbonRequest
from app.schemas.treasury import (
    ApproveKasbonResponse,
    AutoMatchResponse,
    BankAccountCreate,
    BankAccountResponse,
    DisburseKasbonRequest,
    DisburseKasbonResponse,
    ForecastRow,
    ImportStatementRequest,
    KasbonCreate,
    KasbonResponse,
    SettleKasbonRequest,
    SettleKasbonResponse,
    SubmitKasbonResponse,
)

router = APIRouter(prefix="/treasury", tags=["treasury"])

KASBON_ROLES = {
    "FINANCE_OPERATOR",
    "DEPT_HEAD_SALES",
    "DEPT_HEAD_WAREHOUSE",
    "DEPT_HEAD_FA",
    "SUPER_ADMIN",
}
TREASURY_ADMIN = {"DEPT_HEAD_FA", "SUPER_ADMIN"}


# ---------------------------------------------------------------------------
# Bank accounts
# ---------------------------------------------------------------------------


@router.post(
    "/bank-accounts",
    response_model=BankAccountResponse,
    status_code=201,
)
async def create_bank_account(
    payload: BankAccountCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> BankAccountResponse:
    _require_roles(
        current_user,
        {"DEPT_HEAD_FA", "FINANCE_OPERATOR", "SUPER_ADMIN"},
    )
    acct = BankAccount(
        entity_id=current_user["entity_id"],
        bank_name=payload.bank_name,
        account_number=payload.account_number,
        account_name=payload.account_name,
        currency_code=payload.currency_code,
        gl_account_id=payload.gl_account_id,
    )
    db.add(acct)
    try:
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        if "unique" in str(exc.orig).lower():  # type: ignore[union-attr]
            raise HTTPException(
                status_code=409,
                detail="Account number already exists.",
            ) from exc
        raise
    await db.refresh(acct)
    return BankAccountResponse.model_validate(acct)


@router.get(
    "/bank-accounts", response_model=list[BankAccountResponse]
)
async def list_bank_accounts(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[BankAccountResponse]:
    stmt = (
        select(BankAccount)
        .where(BankAccount.entity_id == current_user["entity_id"])
        .order_by(BankAccount.bank_name)
        .limit(100)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [BankAccountResponse.model_validate(a) for a in rows]


# ---------------------------------------------------------------------------
# Kasbon lifecycle
# ---------------------------------------------------------------------------


@router.post("/kasbon", response_model=KasbonResponse, status_code=201)
async def create_kasbon(
    payload: KasbonCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> KasbonResponse:
    """Create a DRAFT kasbon request."""
    _require_roles(current_user, KASBON_ROLES)
    kas = KasbonRequest(
        entity_id=current_user["entity_id"],
        requested_by=current_user["user_id"],
        department_code=payload.department_code,
        amount=Decimal(payload.amount),
        purpose=payload.purpose,
        request_date=payload.request_date,
    )
    db.add(kas)
    try:
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail=str(exc.orig)
        ) from exc
    await db.refresh(kas)
    return KasbonResponse(
        id=kas.id,
        status=str(kas.status),
        amount=str(kas.amount),
        purpose=kas.purpose,
        required_approval_role=(
            str(kas.required_approval_role)
            if kas.required_approval_role
            else None
        ),
    )


@router.get("/kasbon", response_model=list[KasbonResponse])
async def list_kasbon(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[KasbonResponse]:
    stmt = (
        select(KasbonRequest)
        .where(KasbonRequest.entity_id == current_user["entity_id"])
        .order_by(KasbonRequest.request_date.desc())
        .limit(100)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        KasbonResponse(
            id=k.id,
            status=str(k.status),
            amount=str(k.amount),
            purpose=k.purpose,
            required_approval_role=(
                str(k.required_approval_role)
                if k.required_approval_role
                else None
            ),
        )
        for k in rows
    ]


@router.post(
    "/kasbon/{kasbon_id}/submit", response_model=SubmitKasbonResponse
)
async def submit_kasbon(
    kasbon_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> SubmitKasbonResponse:
    _require_roles(current_user, KASBON_ROLES)
    try:
        result = await db.execute(
            text(
                "SELECT fn_submit_kasbon_request("
                "  CAST(:kasbon_id AS uuid)"
                ") AS rpc"
            ),
            {"kasbon_id": kasbon_id},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return SubmitKasbonResponse(
            kasbon_request_id=rpc["kasbon_request_id"],
            required_approval_role=rpc["required_approval_role"],
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.post(
    "/kasbon/{kasbon_id}/approve", response_model=ApproveKasbonResponse
)
async def approve_kasbon(
    kasbon_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> ApproveKasbonResponse:
    # Coarse guard only — real authority check lives in the RPC
    # via fn_get_required_approval_role (dynamic engine).
    _require_roles(current_user, KASBON_ROLES | {"DIREKSI"})
    try:
        result = await db.execute(
            text(
                "SELECT fn_approve_kasbon_request("
                "  CAST(:kasbon_id AS uuid)"
                ") AS rpc"
            ),
            {"kasbon_id": kasbon_id},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return ApproveKasbonResponse(
            kasbon_request_id=rpc["kasbon_request_id"],
            status=rpc["status"],
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.post(
    "/kasbon/{kasbon_id}/disburse",
    response_model=DisburseKasbonResponse,
)
async def disburse_kasbon(
    kasbon_id: str,
    payload: DisburseKasbonRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> DisburseKasbonResponse:
    _require_roles(current_user, TREASURY_ADMIN)
    try:
        result = await db.execute(
            text(
                "SELECT fn_disburse_kasbon("
                "  CAST(:kasbon_id AS uuid),"
                "  CAST(:bank_account_id AS uuid),"
                "  CAST(:piutang_account_id AS uuid)"
                ") AS rpc"
            ),
            {
                "kasbon_id": kasbon_id,
                "bank_account_id": payload.bank_account_id,
                "piutang_account_id": (
                    payload.piutang_karyawan_account_id
                ),
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return DisburseKasbonResponse(
            kasbon_request_id=rpc["kasbon_request_id"],
            journal_entry_id=rpc["journal_entry_id"],
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.post(
    "/kasbon/{kasbon_id}/settle", response_model=SettleKasbonResponse
)
async def settle_kasbon(
    kasbon_id: str,
    payload: SettleKasbonRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> SettleKasbonResponse:
    _require_roles(
        current_user,
        {"FINANCE_OPERATOR", "DEPT_HEAD_FA", "SUPER_ADMIN"},
    )
    lines_json = json.dumps(
        [
            {
                "expense_account_id": str(ln.expense_account_id),
                "description": ln.description,
                "amount": ln.amount,
                "receipt_reference": ln.receipt_reference,
            }
            for ln in payload.lines
        ]
    )
    try:
        result = await db.execute(
            text(
                "SELECT fn_settle_kasbon("
                "  CAST(:kasbon_id AS uuid),"
                "  CAST(:settlement_date AS date),"
                "  CAST(:lines AS jsonb),"
                "  CAST(:piutang_account_id AS uuid),"
                "  CAST(:bank_account_id AS uuid)"
                ") AS rpc"
            ),
            {
                "kasbon_id": kasbon_id,
                "settlement_date": payload.settlement_date,
                "lines": lines_json,
                "piutang_account_id": (
                    payload.piutang_karyawan_account_id
                ),
                "bank_account_id": payload.bank_account_id,
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return SettleKasbonResponse(
            settlement_id=rpc["settlement_id"],
            actual_used=str(rpc["actual_used"]),
            refund=str(rpc["refund"]),
            additional_claim=str(rpc["additional_claim"]),
            journal_entry_id=rpc["journal_entry_id"],
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


# ---------------------------------------------------------------------------
# Bank statements + auto-match
# ---------------------------------------------------------------------------


@router.post(
    "/bank-accounts/{account_id}/statements",
    status_code=201,
)
async def import_bank_statement(
    account_id: str,
    payload: ImportStatementRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> dict:
    _require_roles(
        current_user,
        {"FINANCE_OPERATOR", "DEPT_HEAD_FA", "SUPER_ADMIN"},
    )
    # Verify account belongs to entity (dual-layer).
    stmt = select(BankAccount).where(
        BankAccount.entity_id == current_user["entity_id"],
        BankAccount.id == uuid.UUID(account_id),
    )
    acct = (await db.execute(stmt)).scalar_one_or_none()
    if acct is None:
        raise HTTPException(404, "Bank account not found.")
    for line in payload.lines:
        db.add(
            BankStatementLine(
                bank_account_id=acct.id,
                statement_date=line.statement_date,
                description=line.description,
                amount=Decimal(line.amount),
            )
        )
    await db.commit()
    return {"imported": len(payload.lines)}


@router.post(
    "/bank-accounts/{account_id}/auto-match",
    response_model=AutoMatchResponse,
)
async def auto_match_statement(
    account_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> AutoMatchResponse:
    _require_roles(
        current_user,
        {"FINANCE_OPERATOR", "DEPT_HEAD_FA", "SUPER_ADMIN"},
    )
    try:
        result = await db.execute(
            text(
                "SELECT fn_auto_match_bank_statement("
                "  CAST(:account_id AS uuid)"
                ") AS rpc"
            ),
            {"account_id": account_id},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return AutoMatchResponse(
            matched_count=rpc["matched_count"]
        )
    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


# ---------------------------------------------------------------------------
# Cash flow forecast (read-only)
# ---------------------------------------------------------------------------


@router.get(
    "/forecast", response_model=list[ForecastRow]
)
async def cash_flow_forecast(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
    weeks_ahead: int = 4,
) -> list[ForecastRow]:
    _require_roles(
        current_user,
        {
            "FINANCE_OPERATOR",
            "DEPT_HEAD_FA",
            "SUPER_ADMIN",
            "IT_ADMIN",
        },
    )
    result = await db.execute(
        text(
            "SELECT week_start, category, source_type, "
            "estimated_amount "
            "FROM fn_get_cash_flow_forecast("
            "  CAST(:entity_id AS uuid), "
            "  CAST(:weeks AS int)"
            ")"
        ),
        {
            "entity_id": current_user["entity_id"],
            "weeks": weeks_ahead,
        },
    )
    rows = result.mappings().all()
    return [
        ForecastRow(
            week_start=r["week_start"],
            category=r["category"],
            source_type=r["source_type"],
            estimated_amount=str(r["estimated_amount"]),
        )
        for r in rows
    ]
