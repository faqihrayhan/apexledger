"""
Integration tests for the first-boot setup wizard (Gate 1.4).
"""

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_setup_wizard_full_flow():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Fresh instance reports "not initialized".
        res = await client.get("/api/v1/system/status")
        assert res.status_code == 200
        assert res.json()["is_initialized"] is False

        # 2. Run the setup wizard.
        setup_payload = {
            "entity_code": "OUTPOST",
            "entity_name": "Outpost Test Factory",
            "base_currency_code": "IDR",
            "admin_email": "owner@example.com",
            "admin_full_name": "Hann Owner",
            "admin_password": "SuperSecret123!",
            "fiscal_year": 2026,
        }
        res = await client.post("/api/v1/system/setup", json=setup_payload)
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["entity_code"] == "OUTPOST"
        assert data["periods_created"] == 12
        assert data["access_token"]

        token = data["access_token"]

        # 3. Instance now reports initialized.
        res = await client.get("/api/v1/system/status")
        assert res.json()["is_initialized"] is True

        # 4. The wizard is once-only — a second run must be rejected.
        res = await client.post("/api/v1/system/setup", json=setup_payload)
        assert res.status_code == 409

        # 5. The created admin can log in via the normal auth flow.
        res = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "SuperSecret123!"},
        )
        assert res.status_code == 200
        assert res.json()["role"] == "SUPER_ADMIN"

        # 6. The setup token works on a protected endpoint.
        res = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 200
        assert res.json()["role"] == "SUPER_ADMIN"
        assert res.json()["entity_id"] == data["entity_id"]

    print("\n✅ First-boot setup wizard test PASSED!")
