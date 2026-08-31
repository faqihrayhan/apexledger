"""
HR Payroll API routes (Module 2).

Thin RPC wrappers + typed reads, mirroring the GL router pattern:
- Pydantic validation
- RLS-scoped session (JWT claims injected)
- RPC call
- Error mapping via rpc_errors

Dual-layer defense: reads filter by the caller's entity explicitly.
"""

from __future__ import annotations

import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_with_rls
from app.core.rpc_errors import raise_from_rpc
from app.core.security import get_current_user
from app.models.hr import Employee, PayrollPeriod
from app.schemas.hr import (
    ApproveRequest,
    ApproveResponse,
    CalculateRequest,
    CalculateResponse,
    DisburseRequest,
    DisburseResponse,
    EmployeeCreate,
    EmployeeResponse,
    PayrollPeriodCreate,
    PayrollPeriodResponse,
)

router = APIRouter(prefix="/hr", tags=["HR Payroll"])


def _parse_rpc_json(raw: object) -> dict:
    """Decode an RPC JSONB result (string or decoded object)."""
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)  # type: ignore[arg-type]


def _require_finance_role(current_user: dict) -> None:
    """App-level guard mirroring the RPC role check (dual-layer)."""
    allowed = {"FINANCE_OPERATOR", "DEPT_HEAD_FA", "SUPER_ADMIN"}
    if current_user["role"] not in allowed:
        raise HTTPException(
            status_code=403,
            detail="Only finance roles can manage payroll.",
        )


@router.get("/employees", response_model=list[EmployeeResponse])
async def list_employees(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
    active_only: bool = Query(default=True),
) -> list[EmployeeResponse]:
    """List employees for the current entity."""
    stmt = select(Employee).where(
        Employee.entity_id == current_user["entity_id"]
    )
    if active_only:
        stmt = stmt.where(Employee.is_active.is_(True))
    stmt = stmt.order_by(Employee.employee_code)
    result = await db.execute(stmt)
    employees = result.scalars().all()

    return [
        EmployeeResponse(
            id=e.id,
            employee_code=e.employee_code,
            full_name=e.full_name,
            position=e.position,
            department_code=e.department_code,
            employment_type=e.employment_type,
            base_salary=str(e.base_salary),
            ptkp_status=e.ptkp_status,
            bank_account_no=e.bank_account_no,
            npwp=e.npwp,
            hire_date=e.hire_date,
            termination_date=e.termination_date,
            is_active=e.is_active,
        )
        for e in employees
    ]


@router.post("/employees", response_model=EmployeeResponse, status_code=201)
async def create_employee(
    payload: EmployeeCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> EmployeeResponse:
    """Create an employee (finance roles only)."""
    _require_finance_role(current_user)


    employee = Employee(
        entity_id=current_user["entity_id"],
        employee_code=payload.employee_code,
        full_name=payload.full_name,
        position=payload.position,
        department_code=payload.department_code,
        employment_type=payload.employment_type,
        base_salary=Decimal(payload.base_salary),
        ptkp_status=payload.ptkp_status,
        bank_account_no=payload.bank_account_no,
        npwp=payload.npwp,
        hire_date=payload.hire_date,
        termination_date=payload.termination_date,
        is_active=payload.is_active,
    )
    db.add(employee)
    try:
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        if "unique" in str(exc.orig).lower():  # type: ignore[union-attr]
            from fastapi import HTTPException

            raise HTTPException(
                status_code=409,
                detail=f"Employee code {payload.employee_code} already exists.",
            ) from exc
        raise

    await db.refresh(employee)
    return EmployeeResponse(
        id=employee.id,
        employee_code=employee.employee_code,
        full_name=employee.full_name,
        position=employee.position,
        department_code=employee.department_code,
        employment_type=employee.employment_type,
        base_salary=str(employee.base_salary),
        ptkp_status=employee.ptkp_status,
        bank_account_no=employee.bank_account_no,
        npwp=employee.npwp,
        hire_date=employee.hire_date,
        termination_date=employee.termination_date,
        is_active=employee.is_active,
    )


@router.get("/payroll/periods", response_model=list[PayrollPeriodResponse])
async def list_periods(
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[PayrollPeriodResponse]:
    """List payroll periods for the current entity."""
    _require_finance_role(current_user)

    stmt = (
        select(PayrollPeriod)
        .where(PayrollPeriod.entity_id == current_user["entity_id"])
        .order_by(PayrollPeriod.period_year, PayrollPeriod.period_month)
    )
    result = await db.execute(stmt)
    periods = result.scalars().all()
    return [
        PayrollPeriodResponse(
            id=p.id,
            period_year=p.period_year,
            period_month=p.period_month,
            start_date=p.start_date,
            end_date=p.end_date,
            status=p.status,
            accrual_journal_entry_id=p.accrual_journal_entry_id,
            journal_entry_id=p.journal_entry_id,
        )
        for p in periods
    ]


@router.post(
    "/payroll/periods", response_model=PayrollPeriodResponse, status_code=201
)
async def create_period(
    payload: PayrollPeriodCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> PayrollPeriodResponse:
    """Create a DRAFT payroll period (finance roles only)."""
    _require_finance_role(current_user)

    period = PayrollPeriod(
        entity_id=current_user["entity_id"],
        period_year=payload.period_year,
        period_month=payload.period_month,
        start_date=payload.start_date,
        end_date=payload.end_date,
        status="DRAFT",
    )
    db.add(period)
    try:
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        if "unique" in str(exc.orig).lower():  # type: ignore[union-attr]
            from fastapi import HTTPException

            raise HTTPException(
                status_code=409,
                detail=(
                    "Payroll period "
                    f"{payload.period_year}-{payload.period_month:02d} "
                    "already exists."
                ),
            ) from exc
        raise

    await db.refresh(period)
    return PayrollPeriodResponse(
        id=period.id,
        period_year=period.period_year,
        period_month=period.period_month,
        start_date=period.start_date,
        end_date=period.end_date,
        status=period.status,
        accrual_journal_entry_id=period.accrual_journal_entry_id,
        journal_entry_id=period.journal_entry_id,
    )


@router.post("/payroll/calculate", response_model=CalculateResponse)
async def calculate_entry(
    payload: CalculateRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> CalculateResponse:
    """Calculate payroll for one employee via fn_calculate_payroll_entry."""
    _require_finance_role(current_user)

    try:
        result = await db.execute(
            text(
                "SELECT fn_calculate_payroll_entry("
                "  CAST(:employee_id AS uuid), CAST(:period_id AS uuid)"
                ") AS rpc"
            ),
            {
                "employee_id": str(payload.employee_id),
                "period_id": str(payload.payroll_period_id),
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return CalculateResponse(
            payroll_entry_id=rpc["payroll_entry_id"],
            net_pay=str(rpc["net_pay"]),
        )

    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.post("/payroll/approve", response_model=ApproveResponse)
async def approve_period(
    payload: ApproveRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> ApproveResponse:
    """Approve a payroll period and post the accrual journal."""
    # Only Head of F&A / Super Admin (RPC enforces too).
    allowed = {"DEPT_HEAD_FA", "SUPER_ADMIN"}
    if current_user["role"] not in allowed:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail="Only Head of F&A or Super Admin can approve payroll.",
        )

    try:
        result = await db.execute(
            text(
                "SELECT fn_approve_payroll_period("
                "  CAST(:period_id AS uuid), CAST(:ap_account AS uuid)"
                ") AS rpc"
            ),
            {
                "period_id": str(payload.payroll_period_id),
                "ap_account": str(payload.ap_gaji_account_id),
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return ApproveResponse(
            period_id=rpc["period_id"],
            status=rpc["status"],
            journal_entry_id=rpc["journal_entry_id"],
        )

    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.post("/payroll/disburse", response_model=DisburseResponse)
async def disburse_period(
    payload: DisburseRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> DisburseResponse:
    """Disburse a payroll period (payment journal via AP Gaji)."""
    allowed = {"DEPT_HEAD_FA", "SUPER_ADMIN"}
    if current_user["role"] not in allowed:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail="Only Head of F&A or Super Admin can disburse payroll.",
        )

    try:
        result = await db.execute(
            text(
                "SELECT fn_disburse_payroll_period("
                "  CAST(:period_id AS uuid), CAST(:kas_account AS uuid)"
                ") AS rpc"
            ),
            {
                "period_id": str(payload.payroll_period_id),
                "kas_account": str(payload.kas_bank_account_id),
            },
        )
        rpc = _parse_rpc_json(result.scalar_one())
        return DisburseResponse(
            period_id=rpc["period_id"],
            journal_entry_id=rpc["journal_entry_id"],
            total_net=str(rpc["total_net"]),
        )

    except DBAPIError as exc:
        raise raise_from_rpc(exc) from exc


@router.get("/payroll/periods/{period_id}/entries")
async def list_period_entries(
    period_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List calculated entries for a period (finance roles only)."""
    _require_finance_role(current_user)

    # App-level entity check (dual-layer): the period must belong to
    # the caller's entity before any rows are returned.
    stmt = select(PayrollPeriod).where(
        PayrollPeriod.id == period_id,
        PayrollPeriod.entity_id == current_user["entity_id"],
    )
    period = (await db.execute(stmt)).scalar_one_or_none()
    if period is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Period not found.")

    rows = await db.execute(
        text(
            "SELECT pe.id, pe.employee_id, e.full_name, "
            "       pe.working_days, pe.unpaid_days, pe.overtime_hours, "
            "       pe.gross_earning, pe.total_deduction, pe.net_pay "
            "FROM payroll_entries pe "
            "JOIN employees e ON e.id = pe.employee_id "
            "WHERE pe.payroll_period_id = CAST(:pid AS uuid) "
            "ORDER BY e.full_name"
        ),
        {"pid": period_id},
    )
    return [
        {
            "id": str(row.id),
            "employee_id": str(row.employee_id),
            "full_name": row.full_name,
            "working_days": row.working_days,
            "unpaid_days": row.unpaid_days,
            "overtime_hours": str(row.overtime_hours),
            "gross_earning": str(row.gross_earning),
            "total_deduction": str(row.total_deduction),
            "net_pay": str(row.net_pay),
        }
        for row in rows
    ]
