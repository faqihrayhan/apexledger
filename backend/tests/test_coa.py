"""
Chart of Accounts & Trial Balance integration tests (Gate 2.4/2.5).

The trial balance is the mathematical proof of double-entry integrity:
after posting arbitrary (balanced) journals, the grand totals MUST match.
"""

from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from main import app
from tests.test_gl import _bootstrap_entity, _seed_chart_of_accounts


async def _post_journal(
    client: AsyncClient,
    token: str,
    accounts: dict[str, str],
    lines: list[dict],
    journal_date: str = "2026-03-15",
) -> dict:
    """Create + post a balanced journal entry, return the create response."""
    res = await client.post(
        "/api/v1/gl/journals",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "journal_date": journal_date,
            "currency_code": "IDR",
            "lines": lines,
        },
    )
    assert res.status_code == 201, res.text
    entry = res.json()

    res = await client.post(
        f"/api/v1/gl/journals/{entry['journal_entry_id']}/post",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    return entry


async def test_coa_crud_and_duplicates():
    entity = await _bootstrap_entity("coa-admin@example.com")
    headers = {"Authorization": f"Bearer {entity['token']}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Create
        res = await c.post(
            "/api/v1/gl/accounts",
            headers=headers,
            json={
                "account_code": "1100",
                "account_name": "Bank BCA",
                "account_type": "ASSET",
                "normal_balance": "DEBIT",
            },
        )
        assert res.status_code == 201, res.text
        created = res.json()
        assert created["account_code"] == "1100"
        acc_id = created["id"]

        # Duplicate code -> 409
        res = await c.post(
            "/api/v1/gl/accounts",
            headers=headers,
            json={
                "account_code": "1100",
                "account_name": "Bank BCA Duplicate",
                "account_type": "ASSET",
                "normal_balance": "DEBIT",
            },
        )
        assert res.status_code == 409
        assert res.json()["detail"]["error_code"] == "ACCOUNT_DUPLICATE"

        # Invalid type -> 422 (Pydantic pattern)
        res = await c.post(
            "/api/v1/gl/accounts",
            headers=headers,
            json={
                "account_code": "1200",
                "account_name": "Bad Type",
                "account_type": "NOT_A_TYPE",
                "normal_balance": "DEBIT",
            },
        )
        assert res.status_code == 422

        # Get one
        res = await c.get(f"/api/v1/gl/accounts/{acc_id}", headers=headers)
        assert res.status_code == 200
        assert res.json()["account_name"] == "Bank BCA"

        # Patch (rename)
        res = await c.patch(
            f"/api/v1/gl/accounts/{acc_id}",
            headers=headers,
            json={"account_name": "Bank BCA Utama"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["account_name"] == "Bank BCA Utama"

        # List
        res = await c.get("/api/v1/gl/accounts", headers=headers)
        assert res.status_code == 200
        assert any(a["account_code"] == "1100" for a in res.json())

    print("\n✅ CoA CRUD + duplicate guard PASSED!")


async def test_coa_isolation_and_role_guard():
    """Entity B can't read A's accounts; SALES can't create accounts."""
    from tests.test_gl import _bootstrap_second_entity

    entity_a = await _bootstrap_entity("coa-iso-a@example.com")
    entity_b = await _bootstrap_second_entity("coa-iso-b@example.com")
    headers_a = {"Authorization": f"Bearer {entity_a['token']}"}
    headers_b = {"Authorization": f"Bearer {entity_b['token']}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # A creates an account.
        res = await c.post(
            "/api/v1/gl/accounts",
            headers=headers_a,
            json={
                "account_code": "1300",
                "account_name": "A Only Account",
                "account_type": "ASSET",
                "normal_balance": "DEBIT",
            },
        )
        assert res.status_code == 201, res.text
        acc_id = res.json()["id"]

        # B cannot see it.
        res = await c.get(f"/api/v1/gl/accounts/{acc_id}", headers=headers_b)
        assert res.status_code == 404

        # B's list doesn't include it.
        res = await c.get("/api/v1/gl/accounts", headers=headers_b)
        assert res.status_code == 200
        assert all(a["account_code"] != "1300" for a in res.json())

        # Sales role can't create accounts.
        from sqlalchemy import select

        from app.core.security import create_access_token, hash_password
        from app.db.session import async_session_factory
        from app.models.layer0 import RoleEnum, UserProfile

        async with async_session_factory() as session:
            admin = await session.execute(
                select(UserProfile).where(UserProfile.email == "coa-iso-a@example.com")
            )
            admin_row = admin.scalar_one()
            su = UserProfile(
                entity_id=admin_row.entity_id,
                email="coa-sales@example.com",
                full_name="Sales",
                hashed_password=hash_password("SuperSecret123!"),
                role=RoleEnum.SALES_OPERATOR,
            )
            session.add(su)
            await session.commit()
            sales_id = su.id

        sales_token = create_access_token(
            user_id=sales_id, entity_id=entity_a["entity_id"], role="SALES_OPERATOR"
        )
        res = await c.post(
            "/api/v1/gl/accounts",
            headers={"Authorization": f"Bearer {sales_token}"},
            json={
                "account_code": "9900",
                "account_name": "Sales Acc",
                "account_type": "EXPENSE",
                "normal_balance": "DEBIT",
            },
        )
        assert res.status_code == 403
        assert res.json()["detail"]["error_code"] == "FORBIDDEN_ROLE"

    print("\n✅ CoA isolation + role guard PASSED!")


async def test_trial_balance_math_proof():
    """Post several balanced journals, then the trial balance must balance."""
    entity = await _bootstrap_entity("tb-admin@example.com")
    headers = {"Authorization": f"Bearer {entity['token']}"}
    accounts = await _seed_chart_of_accounts(entity["entity_id"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Journal 1: cash sale 500k (1001 D / 4001 C)
        await _post_journal(
            c, entity["token"], accounts,
            [
                {"account_id": accounts["1001"], "debit_amount": "500000", "credit_amount": "0"},
                {"account_id": accounts["4001"], "debit_amount": "0", "credit_amount": "500000"},
            ],
        )
        # Journal 2: expense paid by cash 75k (5101 D / 1001 C)
        await _post_journal(
            c, entity["token"], accounts,
            [
                {"account_id": accounts["5101"], "debit_amount": "75000", "credit_amount": "0"},
                {"account_id": accounts["1001"], "debit_amount": "0", "credit_amount": "75000"},
            ],
        )
        # Journal 3: unbalanced-but-valid multi-line (3 lines):
        # 1001 D 100k, 4001 C 60k, 5101 D 40k  -> D total 140k = C total 60+?
        # Actually: D=140k, C=60k -> unbalanced, would fail. Use:
        # 1001 D 100k, 4001 C 100k... keep it simple but different amounts.
        await _post_journal(
            c, entity["token"], accounts,
            [
                {"account_id": accounts["1001"], "debit_amount": "100000", "credit_amount": "0"},
                {"account_id": accounts["4001"], "debit_amount": "0", "credit_amount": "100000"},
            ],
        )

        # A DRAFT (unposted) journal must NOT count toward the balance.
        res = await c.post(
            "/api/v1/gl/journals",
            headers=headers,
            json={
                "journal_date": "2026-03-15",
                "currency_code": "IDR",
                "lines": [
                    {"account_id": accounts["1001"], "debit_amount": "999", "credit_amount": "0"},
                    {"account_id": accounts["4001"], "debit_amount": "0", "credit_amount": "999"},
                ],
            },
        )
        assert res.status_code == 201

        # Fetch the trial balance.
        res = await c.get(
            "/api/v1/gl/reports/trial-balance",
            headers=headers,
            params={"as_of": "2026-12-31"},
        )
        assert res.status_code == 200, res.text
        tb = res.json()

        # THE MATH PROOF: grand debit == grand credit.
        assert tb["is_balanced"] is True
        assert Decimal(tb["grand_total_debit"]) == Decimal(tb["grand_total_credit"])

        # Expected account-level numbers:
        # 1001: D 600k, C 75k -> net D 525k
        # 4001: C 600k        -> net C 600k
        # 5101: D 75k         -> net D 75k
        # Grand: net D 525k+75k = 600k == net C 600k ✅
        by_code = {r["account_code"]: r for r in tb["rows"]}
        assert Decimal(by_code["1001"]["net_debit"]) == Decimal("525000")
        assert Decimal(by_code["4001"]["net_credit"]) == Decimal("600000")
        assert Decimal(by_code["5101"]["net_debit"]) == Decimal("75000")
        assert Decimal(tb["grand_total_debit"]) == Decimal("600000")

        # The DRAFT journal (999) must not appear in any totals:
        # 1001 total_debit would be 600999 if drafts were counted.
        assert Decimal(by_code["1001"]["total_debit"]) == Decimal("600000")

        # As-of date filtering: journal before the date counts, after not.
        res = await c.get(
            "/api/v1/gl/reports/trial-balance",
            headers=headers,
            params={"as_of": "2026-02-01"},
        )
        assert res.status_code == 200
        tb_feb = res.json()
        # All journals were dated 2026-03-15 — nothing posted before Feb.
        assert Decimal(tb_feb["grand_total_debit"]) == 0
        assert Decimal(tb_feb["grand_total_credit"]) == 0
        assert tb_feb["is_balanced"] is True

    print("\n✅ Trial balance math proof PASSED!")


async def test_deactivate_flow():
    """Accounts with history soft-deactivate; unused ones hard-delete."""
    entity = await _bootstrap_entity("del-admin@example.com")
    headers = {"Authorization": f"Bearer {entity['token']}"}
    accounts = await _seed_chart_of_accounts(entity["entity_id"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # 1. Unused account -> hard delete.
        res = await c.post(
            "/api/v1/gl/accounts",
            headers=headers,
            json={
                "account_code": "9900",
                "account_name": "Temp Account",
                "account_type": "EXPENSE",
                "normal_balance": "DEBIT",
            },
        )
        assert res.status_code == 201, res.text
        temp_id = res.json()["id"]

        res = await c.delete(f"/api/v1/gl/accounts/{temp_id}", headers=headers)
        assert res.status_code == 204
        res = await c.get(f"/api/v1/gl/accounts/{temp_id}", headers=headers)
        assert res.status_code == 404

        # 2. Account with journal history -> soft-deactivate only.
        await _post_journal(
            c, entity["token"], accounts,
            [
                {"account_id": accounts["1001"], "debit_amount": "100", "credit_amount": "0"},
                {"account_id": accounts["4001"], "debit_amount": "0", "credit_amount": "100"},
            ],
        )
        res = await c.delete(
            f"/api/v1/gl/accounts/{accounts['1001']}", headers=headers
        )
        assert res.status_code == 204

        res = await c.get(
            f"/api/v1/gl/accounts/{accounts['1001']}", headers=headers
        )
        assert res.status_code == 200
        assert res.json()["is_active"] is False

    print("\n✅ Deactivate flow (soft vs hard) PASSED!")
