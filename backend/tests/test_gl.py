"""
Module 1 integration tests — double-entry engine via the API (Gate 2.3).

Full lifecycle verified through HTTP, exercising:
- fn_create_journal_entry (validation, balance check, numbering)
- fn_post_journal_entry (status transition, period check)
- fn_reverse_journal_entry (mirror entry, immutability)
- RLS scoping (entity isolation)
- RPC error mapping (P0001 -> HTTP 422/401/403)
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import async_session_factory, inject_rls_context
from app.models.gl import ChartOfAccounts
from app.models.layer0 import RoleEnum, UserProfile
from main import app


async def _bootstrap_entity(admin_email: str) -> dict:
    """Run the setup wizard and return {entity_id, token, ...}.

    NOTE: The wizard is once-only per instance. For the second entity in
    a multi-entity test, use ``_bootstrap_second_entity`` instead.
    """
    suffix = uuid.uuid4().hex[:8]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.post(
            "/api/v1/system/setup",
            json={
                "entity_code": f"ENT{suffix}",
                "entity_name": "Journal Test Entity",
                "base_currency_code": "IDR",
                "admin_email": admin_email,
                "admin_full_name": "Finance Admin",
                "admin_password": "SuperSecret123!",
                "fiscal_year": 2026,
            },
        )
        assert res.status_code == 201, res.text
        data = res.json()
        return {
            "entity_id": data["entity_id"],
            "token": data["access_token"],
        }


async def _bootstrap_second_entity(admin_email: str) -> dict:
    """Create an additional entity + SUPER_ADMIN directly (wizard is once-only)."""
    from calendar import monthrange

    from app.core.security import create_access_token, hash_password
    from app.models.gl import FiscalPeriod, FiscalYear
    from app.models.layer0 import Entity, RoleEnum, UserProfile

    async with async_session_factory() as session:
        entity = Entity(
            code=f"ENT{uuid.uuid4().hex[:8]}",
            name="Second Entity",
            base_currency_code="IDR",
        )
        session.add(entity)
        await session.flush()

        admin = UserProfile(
            entity_id=entity.id,
            email=admin_email,
            full_name="Second Admin",
            hashed_password=hash_password("SuperSecret123!"),
            role=RoleEnum.SUPER_ADMIN,
        )
        session.add(admin)
        await session.flush()

        fy = FiscalYear(
            entity_id=entity.id,
            year_label="FY2026",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        session.add(fy)
        await session.flush()
        for month in range(1, 13):
            session.add(
                FiscalPeriod(
                    fiscal_year_id=fy.id,
                    period_number=month,
                    start_date=date(2026, month, 1),
                    end_date=date(2026, month, monthrange(2026, month)[1]),
                )
            )
        await session.commit()

        token = create_access_token(
            user_id=admin.id, entity_id=entity.id, role=RoleEnum.SUPER_ADMIN.value
        )
        return {"entity_id": str(entity.id), "token": token}


async def _seed_chart_of_accounts(entity_id: str) -> dict[str, str]:
    """Create a minimal chart of accounts (postable accounts only)."""
    accounts = {
        "1001": ("Cash on Hand", "ASSET", "DEBIT"),
        "4001": ("Sales Revenue", "REVENUE", "CREDIT"),
        "5101": ("Office Expense", "EXPENSE", "DEBIT"),
    }
    account_ids = {}
    async with async_session_factory() as session:
        await inject_rls_context(
            session,
            {
                "user_id": "00000000-0000-0000-0000-000000000000",
                "entity_id": entity_id,
                "role": "SUPER_ADMIN",
            },
        )
        for code, (name, acc_type, normal) in accounts.items():
            acct = ChartOfAccounts(
                entity_id=entity_id,
                account_code=code,
                account_name=name,
                account_type=acc_type,
                normal_balance=normal,
            )
            session.add(acct)
        await session.commit()

        # Re-fetch to get generated UUIDs.
        result = await session.execute(
            select(ChartOfAccounts.account_code, ChartOfAccounts.id)
            .where(ChartOfAccounts.entity_id == entity_id)
        )
        for code, acc_id in result.all():
            account_ids[code] = str(acc_id)
    return account_ids


from sqlalchemy import select  # noqa: E402  (used inside _seed_chart_of_accounts)


@pytest.mark.asyncio
async def test_full_journal_lifecycle():
    entity = await _bootstrap_entity("finops@example.com")
    headers = {"Authorization": f"Bearer {entity['token']}"}
    accounts = await _seed_chart_of_accounts(entity["entity_id"])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # --- 1. Balanced entry is accepted (DRAFT) ---
        res = await client.post(
            "/api/v1/gl/journals",
            headers=headers,
            json={
                "journal_date": "2026-03-15",
                "description": "Cash sales for the day",
                "currency_code": "IDR",
                "lines": [
                    {
                        "account_id": accounts["1001"],
                        "debit_amount": "500000",
                        "credit_amount": "0",
                    },
                    {
                        "account_id": accounts["4001"],
                        "debit_amount": "0",
                        "credit_amount": "500000",
                    },
                ],
            },
        )
        assert res.status_code == 201, res.text
        created = res.json()
        assert created["status"] == "DRAFT"
        assert created["journal_number"].startswith("JE-202603-")
        je_id = created["journal_entry_id"]

        # --- 2. Unbalanced entry is rejected with the RPC error code ---
        res = await client.post(
            "/api/v1/gl/journals",
            headers=headers,
            json={
                "journal_date": "2026-03-15",
                "currency_code": "IDR",
                "lines": [
                    {
                        "account_id": accounts["1001"],
                        "debit_amount": "100000",
                        "credit_amount": "0",
                    },
                    {
                        "account_id": accounts["4001"],
                        "debit_amount": "0",
                        "credit_amount": "90000",
                    },
                ],
            },
        )
        assert res.status_code == 422
        assert res.json()["detail"]["error_code"] == "JE_UNBALANCED"

        # --- 3. Single-line entry is rejected ---
        res = await client.post(
            "/api/v1/gl/journals",
            headers=headers,
            json={
                "journal_date": "2026-03-15",
                "currency_code": "IDR",
                "lines": [
                    {
                        "account_id": accounts["1001"],
                        "debit_amount": "50000",
                        "credit_amount": "0",
                    },
                ],
            },
        )
        assert res.status_code == 422
        assert res.json()["detail"]["error_code"] == "JE_MIN_LINES"

        # --- 4. Unauthenticated call is rejected ---
        res = await client.post(
            "/api/v1/gl/journals",
            json={
                "journal_date": "2026-03-15",
                "currency_code": "IDR",
                "lines": [
                    {
                        "account_id": accounts["1001"],
                        "debit_amount": "1",
                        "credit_amount": "0",
                    },
                    {
                        "account_id": accounts["4001"],
                        "debit_amount": "0",
                        "credit_amount": "1",
                    },
                ],
            },
        )
        assert res.status_code == 401

        # --- 5. Post the draft ---
        res = await client.post(
            f"/api/v1/gl/journals/{je_id}/post", headers=headers
        )
        assert res.status_code == 200, res.text
        posted = res.json()
        assert posted["status"] == "POSTED"
        # Amounts are serialized as strings (Decimal precision).
        assert Decimal(posted["debit_total"]) == Decimal(posted["credit_total"]) == 500000

        # --- 6. Posting twice is rejected ---
        res = await client.post(
            f"/api/v1/gl/journals/{je_id}/post", headers=headers
        )
        assert res.status_code == 422
        assert res.json()["detail"]["error_code"] == "JE_INVALID_STATUS"

        # --- 7. List shows the entry with totals ---
        res = await client.get("/api/v1/gl/journals", headers=headers)
        assert res.status_code == 200
        entries = res.json()
        assert any(e["journal_number"] == created["journal_number"] for e in entries)
        entry = next(e for e in entries if e["journal_number"] == created["journal_number"])
        assert Decimal(entry["total_amount"]) == 500000
        assert entry["line_count"] == 2

        # --- 8. Reverse the posted entry ---
        res = await client.post(
            f"/api/v1/gl/journals/{je_id}/reverse",
            headers=headers,
            json={"reversal_date": "2026-03-20", "reason": "Wrong entry"},
        )
        assert res.status_code == 200, res.text
        rev = res.json()
        assert rev["original_status"] == "REVERSED"
        assert rev["reversal_number"].endswith("-REV")

        # --- 9. Reversing twice is rejected ---
        res = await client.post(
            f"/api/v1/gl/journals/{je_id}/reverse",
            headers=headers,
            json={"reversal_date": "2026-03-21", "reason": "Again"},
        )
        assert res.status_code == 422
        assert res.json()["detail"]["error_code"] == "JE_ALREADY_REVERSED"

    print("\n✅ Full journal lifecycle (create -> post -> reverse) PASSED!")


@pytest.mark.asyncio
async def test_rls_entity_isolation():
    """A user from entity B must not see entity A's journals."""
    entity_a = await _bootstrap_entity("isolated-a@example.com")
    accounts_a = await _seed_chart_of_accounts(entity_a["entity_id"])
    entity_b = await _bootstrap_second_entity("isolated-b@example.com")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Entity A creates a journal.
        res = await client.post(
            "/api/v1/gl/journals",
            headers={"Authorization": f"Bearer {entity_a['token']}"},
            json={
                "journal_date": "2026-03-15",
                "currency_code": "IDR",
                "lines": [
                    {
                        "account_id": accounts_a["1001"],
                        "debit_amount": "1000",
                        "credit_amount": "0",
                    },
                    {
                        "account_id": accounts_a["4001"],
                        "debit_amount": "0",
                        "credit_amount": "1000",
                    },
                ],
            },
        )
        assert res.status_code == 201

        # Entity B lists journals — must see ZERO entries from A.
        res = await client.get(
            "/api/v1/gl/journals",
            headers={"Authorization": f"Bearer {entity_b['token']}"},
        )
        assert res.status_code == 200
        assert res.json() == []

    print("\n✅ RLS entity isolation test PASSED!")


@pytest.mark.asyncio
async def test_non_finance_role_cannot_create():
    """SALES_OPERATOR must be forbidden from creating journals."""
    entity = await _bootstrap_entity("rolecheck@example.com")
    accounts = await _seed_chart_of_accounts(entity["entity_id"])

    # Create a second user with SALES_OPERATOR role in the same entity.
    async with async_session_factory() as session:
        admin = await session.execute(
            select(UserProfile).where(UserProfile.email == "rolecheck@example.com")
        )
        admin_row = admin.scalar_one()

        sales_user = UserProfile(
            entity_id=admin_row.entity_id,
            email="salesperson@example.com",
            full_name="Sales Person",
            hashed_password="x" * 60,
            role=RoleEnum.SALES_OPERATOR,
        )
        session.add(sales_user)
        await session.commit()

    from app.core.security import create_access_token

    sales_token = create_access_token(
        user_id=uuid.uuid4(),  # demo token: role check happens in the RPC
        entity_id=entity["entity_id"],
        role="SALES_OPERATOR",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.post(
            "/api/v1/gl/journals",
            headers={"Authorization": f"Bearer {sales_token}"},
            json={
                "journal_date": "2026-03-15",
                "currency_code": "IDR",
                "lines": [
                    {
                        "account_id": accounts["1001"],
                        "debit_amount": "10",
                        "credit_amount": "0",
                    },
                    {
                        "account_id": accounts["4001"],
                        "debit_amount": "0",
                        "credit_amount": "10",
                    },
                ],
            },
        )
        assert res.status_code == 403
        assert res.json()["detail"]["error_code"] == "FORBIDDEN_ROLE"

    print("\n✅ Role guard test PASSED!")
