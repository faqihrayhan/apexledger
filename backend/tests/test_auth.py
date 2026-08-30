"""
Integration tests for the JWT Auth system and RLS context injection.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import async_session_factory
from app.models.layer0 import Entity
from main import app


@pytest.mark.asyncio
async def test_auth_and_jwt_lifecycle():
    # 1. Setup: create a fresh entity with a unique code (idempotent re-runs)
    unique_suffix = uuid.uuid4().hex[:8]
    entity_code = f"CORP_{unique_suffix}"
    email = f"admin_{unique_suffix}@example.com"

    async with async_session_factory() as session:
        entity = Entity(
            code=entity_code,
            name="Test Corporation",
            base_currency_code="IDR",
        )
        session.add(entity)
        await session.commit()
        entity_id = entity.id

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 2. Test Register
        register_payload = {
            "entity_id": str(entity_id),
            "email": email,
            "full_name": "Test Admin",
            "password": "SecurePassword123!",
            "role": "SUPER_ADMIN",
        }
        res = await client.post("/api/v1/auth/register", json=register_payload)
        assert res.status_code == 201, res.text
        reg_data = res.json()
        assert "access_token" in reg_data
        assert reg_data["email"] == email

        # 3. Test Login
        login_payload = {
            "email": email,
            "password": "SecurePassword123!",
        }
        res_login = await client.post("/api/v1/auth/login", json=login_payload)
        assert res_login.status_code == 200, res_login.text
        token = res_login.json()["access_token"]
        assert token is not None

        # 4. Test Authenticated Route (/auth/me) using the Token
        headers = {"Authorization": f"Bearer {token}"}
        res_me = await client.get("/api/v1/auth/me", headers=headers)
        assert res_me.status_code == 200, res_me.text
        me_data = res_me.json()
        assert me_data["role"] == "SUPER_ADMIN"
        assert me_data["entity_id"] == str(entity_id)

        # 5. Negative test: wrong password must be rejected
        res_bad = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "WrongPassword!"},
        )
        assert res_bad.status_code == 401

    print("\n✅ JWT Auth lifecycle test PASSED!")
