"""
Budgeting & Analytics API routes (Module 8).

Budget lifecycle (create -> approve -> lock -> revise with
audit snapshot), budget-vs-actual variance reporting, monthly
trend analysis, and the employee productivity batch.

Business rules live in the PL/pgSQL RPCs; this layer enforces
authentication, coarse role guards, and entity scoping via RLS.
"""

from __future__ import annotations

import json
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_with_rls
from app.api.v1.sales import _parse_rpc_json, _require_roles
from app.core.rpc_errors import raise_from_rpc
from app.core.security import get_current_user
from app.schemas.budgeting import (
    BudgetLineOut,
    BudgetListOut,
    BudgetStatusResponse,
    BudgetVsActualRow,
    CreateBudgetRequest,
    CreateBudgetResponse,
    FiscalYearOut,
    MonthlyTrendRow,
    ProductivityBatchResponse,
    ReviseBudgetRequest,
    ReviseBudgetResponse,
)

router = APIRouter(prefix="/budgeting", tags=["Budgeting & Analytics"])

BUDGET_ROLES = {"DEPT_HEAD_FA", "SUPER_ADMIN"}
READ_ROLES = {
    "FINANCE_OPERATOR",
    "DEPT_HEAD_FA",
    "DEPT_HEAD_SALES",
    "DEPT_HEAD_WAREHOUSE",
    "SUPER_ADMIN",
}


def _amt(v: object) -> str:
    """Serialize a Decimal amount without scientific notation."""
    if isinstance(v, Decimal):
        return format(v, "f")
    return str(v)


def _lines_to_jsonb(lines) -> str:
    """Build the p_lines JSONB payload string."""
    return json.dumps(
        [
            {
                "account_id": str(ln.account_id),
                "department_code": ln.department_code,
                "period_month": ln.period_month,
                "budgeted_amount": ln.budgeted_amount,
            }
            for ln in lines

        ]
    )


@router.post("/budgets", response_model=CreateBudgetResponse)
async def create_budget(
    payload: CreateBudgetRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> CreateBudgetResponse:
    """Create an annual budget (status DRAFT) with lines."""
    _require_roles(current_user, BUDGET_ROLES)

    try:
        result = await db.execute(
            text(
                "SELECT fn_create_annual_budget("
                "CAST(:entity_id AS uuid), "
                "CAST(:fiscal_year_id AS uuid), "
                ":budget_name, "
                "CAST(:lines AS jsonb))"
            ),
            {
                "entity_id": current_user["entity_id"],
                "fiscal_year_id": payload.fiscal_year_id,
                "budget_name": payload.budget_name,
                "lines": _lines_to_jsonb(payload.lines),
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        raise raise_from_rpc(exc) from exc

    return CreateBudgetResponse(budget_id=rpc["budget_id"])


@router.post(
    "/budgets/{budget_id}/approve",
    response_model=BudgetStatusResponse,
)
async def approve_budget(
    budget_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> BudgetStatusResponse:
    """Approve a DRAFT budget (DEPT_HEAD_FA / SUPER_ADMIN)."""
    _require_roles(current_user, BUDGET_ROLES)

    try:
        result = await db.execute(
            text(
                "SELECT fn_approve_budget("
                "CAST(:budget_id AS uuid))"
            ),
            {"budget_id": budget_id},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        raise raise_from_rpc(exc) from exc

    return BudgetStatusResponse(
        budget_id=rpc["budget_id"], status=rpc["status"]
    )


@router.post(
    "/budgets/{budget_id}/lock",
    response_model=BudgetStatusResponse,
)
async def lock_budget(
    budget_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> BudgetStatusResponse:
    """Lock an APPROVED budget (SUPER_ADMIN only)."""
    _require_roles(current_user, {"SUPER_ADMIN"})

    try:
        result = await db.execute(
            text(
                "SELECT fn_lock_budget("
                "CAST(:budget_id AS uuid))"
            ),
            {"budget_id": budget_id},
        )
        rpc = _parse_rpc_json(result.scalar_one())
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        raise raise_from_rpc(exc) from exc

    return BudgetStatusResponse(
        budget_id=rpc["budget_id"], status=rpc["status"]
    )


@router.post(
    "/budgets/{budget_id}/revise",
    response_model=ReviseBudgetResponse,
)
async def revise_budget(
    budget_id: str,
    payload: ReviseBudgetRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> ReviseBudgetResponse:
    """Revise an APPROVED/LOCKED budget with audit snapshot."""
    _require_roles(current_user, BUDGET_ROLES)

    try:
        result = await db.execute(
            text(
                "SELECT fn_revise_budget("
                "CAST(:budget_id AS uuid), "
                "CAST(:lines AS jsonb), :reason)"
            ),
            {
                "budget_id": budget_id,
                "lines": _lines_to_jsonb(payload.lines),
                "reason": payload.reason,
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        raise raise_from_rpc(exc) from exc

    return ReviseBudgetResponse(
        budget_id=rpc["budget_id"],
        revision_number=rpc["revision_number"],
    )


@router.get(
    "/budgets/{budget_id}/vs-actual",
    response_model=list[BudgetVsActualRow],
)
async def get_budget_vs_actual(
    budget_id: str,
    as_of_month: int,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[BudgetVsActualRow]:
    """Budget vs actual variance report (read-only)."""
    _require_roles(current_user, READ_ROLES)

    result = await db.execute(
        text(
            "SELECT account_code, account_name, "
            "department_code, budgeted_amount, "
            "actual_amount, variance_amount, "
            "variance_pct "
            "FROM fn_get_budget_vs_actual("
            "CAST(:budget_id AS uuid), "
            "CAST(:m AS smallint))"
        ),
        {"budget_id": budget_id, "m": as_of_month},
    )
    return [
        BudgetVsActualRow(
            account_code=r[0],
            account_name=r[1],
            department_code=r[2],
            budgeted_amount=_amt(r[3]),
            actual_amount=_amt(r[4]),
            variance_amount=_amt(r[5]),
            variance_pct=(
                _amt(r[6]) if r[6] is not None else None
            ),
        )
        for r in result.fetchall()
    ]


@router.get(
    "/trend", response_model=list[MonthlyTrendRow]
)
async def get_monthly_trend(
    account_type: str,
    num_months: int = 12,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[MonthlyTrendRow]:
    """Monthly trend for REVENUE/EXPENSE (read-only)."""
    _require_roles(current_user, READ_ROLES)

    result = await db.execute(
        text(
            "SELECT period_year, period_month, "
            "total_amount FROM fn_get_monthly_trend("
            "CAST(:entity_id AS uuid), "
            "CAST(:account_type AS account_type_enum), "
            "CAST(:n AS int))"
        ),
        {
            "entity_id": current_user["entity_id"],
            "account_type": account_type,
            "n": num_months,
        },
    )
    return [
        MonthlyTrendRow(
            period_year=r[0],
            period_month=r[1],
            total_amount=_amt(r[2]),
        )
        for r in result.fetchall()
    ]


@router.post(
    "/productivity/batch",
    response_model=ProductivityBatchResponse,
)
async def run_productivity_batch(
    period_year: int,
    period_month: int,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> ProductivityBatchResponse:
    """Run the employee productivity batch (idempotent)."""
    _require_roles(current_user, BUDGET_ROLES)

    try:
        result = await db.execute(
            text(
                "SELECT "
                "fn_calculate_employee_productivity_batch("
                "CAST(:entity_id AS uuid), "
                "CAST(:y AS smallint), "
                "CAST(:m AS smallint))"
            ),
            {
                "entity_id": current_user["entity_id"],
                "y": period_year,
                "m": period_month,
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        raise raise_from_rpc(exc) from exc

    return ProductivityBatchResponse(
        metrics_calculated=rpc["metrics_calculated"]
    )


# ---------------------------------------------------------------------------
# Read-only helpers (UI support — no business logic, no migration)
# ---------------------------------------------------------------------------


@router.get("/fiscal-years", response_model=list[FiscalYearOut])
async def list_fiscal_years(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[FiscalYearOut]:
    """List fiscal years for the current entity (for budget forms)."""
    result = await db.execute(
        text(
            "SELECT id, year_label, start_date, end_date, status "
            "FROM fiscal_years "
            "WHERE entity_id = CAST(:entity_id AS uuid) "
            "ORDER BY start_date"
        ),
        {"entity_id": current_user["entity_id"]},
    )
    return [
        FiscalYearOut(
            id=r[0],
            year_label=r[1],
            start_date=r[2],
            end_date=r[3],
            status=r[4],
        )
        for r in result.fetchall()
    ]


@router.get("/budgets", response_model=list[BudgetListOut])
async def list_budgets(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[BudgetListOut]:
    """List budgets for the current entity with fiscal year labels."""
    result = await db.execute(
        text(
            "SELECT b.id, b.budget_name, b.fiscal_year_id, "
            "fy.year_label, b.status, b.created_at "
            "FROM budgets b "
            "JOIN fiscal_years fy ON fy.id = b.fiscal_year_id "
            "WHERE b.entity_id = CAST(:entity_id AS uuid) "
            "ORDER BY b.created_at"
        ),
        {"entity_id": current_user["entity_id"]},
    )
    return [
        BudgetListOut(
            id=r[0],
            budget_name=r[1],
            fiscal_year_id=r[2],
            year_label=r[3],
            status=r[4],
            created_at=r[5],
        )
        for r in result.fetchall()
    ]


@router.get(
    "/budgets/{budget_id}/lines", response_model=list[BudgetLineOut]
)
async def list_budget_lines(
    budget_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[BudgetLineOut]:
    """List budget lines with account codes (for revise forms)."""
    result = await db.execute(
        text(
            "SELECT bl.id, bl.account_id, coa.account_code, "
            "coa.account_name, bl.department_code, "
            "bl.period_month, bl.budgeted_amount "
            "FROM budget_lines bl "
            "JOIN budgets b ON b.id = bl.budget_id "
            "JOIN chart_of_accounts coa "
            "  ON coa.id = bl.account_id "
            "WHERE b.entity_id = CAST(:entity_id AS uuid) "
            "AND bl.budget_id = CAST(:budget_id AS uuid) "
            "ORDER BY coa.account_code, bl.period_month"
        ),
        {
            "entity_id": current_user["entity_id"],
            "budget_id": budget_id,
        },
    )
    return [
        BudgetLineOut(
            id=r[0],
            account_id=r[1],
            account_code=r[2],
            account_name=r[3],
            department_code=r[4],
            period_month=r[5],
            budgeted_amount=_amt(r[6]),
        )
        for r in result.fetchall()
    ]
