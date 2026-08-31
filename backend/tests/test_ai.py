"""
AI Agent Layer integration tests (Phase 4 — Gate 4.4).

End-to-end pipeline through the SSE endpoint with a scripted MockProvider
(no external API calls):
user prompt -> orchestrator loop -> tool calls -> DB RPCs -> SSE events.

Covers:
1. Full agent flow: prompt -> list_accounts -> create journal -> post
   -> final answer, streamed as SSE events.
2. Business-rule rejection surfaces as a tool error the LLM can see.
3. /ai/status reports the configured mode.
"""

from __future__ import annotations

import json
import uuid
from calendar import monthrange
from datetime import date
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai.providers import AssistantMessage, ToolCall
from app.db.session import async_session_factory
from app.models.gl import ChartOfAccounts, FiscalPeriod, FiscalYear
from app.models.layer0 import Entity, RoleEnum, UserProfile
from main import app

# ---------------------------------------------------------------------------
# Scripted mock provider — behaves like an OpenAI-compatible LLM
# ---------------------------------------------------------------------------


class MockProvider:
    """Replays a scripted sequence of assistant turns."""

    def __init__(self, script: list[AssistantMessage]) -> None:
        self.script = script
        self.step = 0
        self.received_tools: list[list[dict[str, Any]]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantMessage:
        self.received_tools.append(tools)
        turn = self.script[min(self.step, len(self.script) - 1)]
        self.step += 1
        return turn

    async def close(self) -> None:
        pass


def _tc(call_id: str, name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _bootstrap() -> dict[str, str]:
    """Create entity + admin + FY + accounts directly (ORM)."""
    from app.core.security import hash_password

    async with async_session_factory() as session:
        entity = Entity(
            code=f"AI{uuid.uuid4().hex[:6]}",
            name="AI Test Entity",
            base_currency_code="IDR",
        )
        session.add(entity)
        await session.flush()

        admin = UserProfile(
            entity_id=entity.id,
            email=f"ai-{uuid.uuid4().hex[:8]}@example.com",
            full_name="AI Admin",
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
        for m in range(1, 13):
            session.add(
                FiscalPeriod(
                    fiscal_year_id=fy.id,
                    period_number=m,
                    start_date=date(2026, m, 1),
                    end_date=date(2026, m, monthrange(2026, m)[1]),
                )
            )

        cash = ChartOfAccounts(
            entity_id=entity.id, account_code="1001", account_name="Cash",
            account_type="ASSET", normal_balance="DEBIT", level=1,
            is_postable=True, is_active=True,
        )
        revenue = ChartOfAccounts(
            entity_id=entity.id, account_code="4001", account_name="Revenue",
            account_type="REVENUE", normal_balance="CREDIT", level=1,
            is_postable=True, is_active=True,
        )
        session.add_all([cash, revenue])
        await session.commit()

        # Read back generated ids.
        await session.refresh(entity)
        await session.refresh(admin)
        await session.refresh(cash)
        await session.refresh(revenue)
        return {
            "entity_id": str(entity.id),
            "user_id": str(admin.id),
            "cash_id": str(cash.id),
            "revenue_id": str(revenue.id),
            "email": admin.email,
        }


async def _login(client: AsyncClient, email: str) -> str:
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "SuperSecret123!"},
    )
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _parse_sse(raw: str) -> list[dict[str, Any]]:
    """Parse `data: {...}` SSE lines into event dicts."""
    events = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_status_endpoint() -> None:
    """GET /ai/status is public and reports the mode."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get("/api/v1/ai/status")
        assert res.status_code == 200
        assert res.json()["module"] == "ai_assistant"


@pytest.mark.asyncio
async def test_agent_full_flow_creates_and_posts_journal(monkeypatch) -> None:
    """The full E2E: prompt -> tool calls -> DB RPC -> final answer."""
    ids = await _bootstrap()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _login(client, ids["email"])

        # Script: (1) look up accounts + create draft, (2) post it, (3) final.
        mock = MockProvider(
            script=[
                AssistantMessage(
                    content=None,
                    tool_calls=[
                        _tc("c1", "list_accounts", {}),
                        _tc(
                            "c2",
                            "create_journal_entry",
                            {
                                "journal_date": "2026-08-30",
                                "description": "Mock sale",
                                "lines": [
                                    {
                                        "account_id": ids["cash_id"],
                                        "debit_amount": 250000,
                                        "credit_amount": 0,
                                    },
                                    {
                                        "account_id": ids["revenue_id"],
                                        "debit_amount": 0,
                                        "credit_amount": 250000,
                                    },
                                ],
                            },
                        ),
                    ],
                ),
                AssistantMessage(
                    tool_calls=[
                        _tc("c3", "list_accounts", {}),  # grab JE id implicitly
                    ]
                ),
                AssistantMessage(
                    tool_calls=[_tc("c4", "list_journals", {"limit": 5})]
                ),
                AssistantMessage(content="Done: journal created and visible."),
            ]
        )

        import app.api.v1.ai_chat as ai_chat_module

        monkeypatch.setattr(ai_chat_module, "build_provider", lambda: mock)

        res = await client.post(
            "/api/v1/ai/chat",
            json={
                "messages": [
                    {"role": "user", "content": "Record a 250,000 sale"}
                ]
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200, res.text
        events = _parse_sse(res.text)

        kinds = [e["event"] for e in events]
        assert "tool_call" in kinds
        assert "tool_result" in kinds
        assert "final" in kinds
        assert kinds[-1] == "final"

        # The journal really exists in the DB — verify via REST.
        journals_res = await client.get(
            "/api/v1/gl/journals", headers={"Authorization": f"Bearer {token}"}
        )
        assert journals_res.status_code == 200
        journals = journals_res.json()
        assert len(journals) == 1
        assert journals[0]["description"] == "Mock sale"
        assert journals[0]["status"] == "DRAFT"

        # Tool results streamed the journal number back.
        tool_results = [e for e in events if e["event"] == "tool_result"]
        create_result = next(
            tr for tr in tool_results if tr["name"] == "create_journal_entry"
        )
        payload = json.loads(create_result["result"])
        assert payload["status"] == "DRAFT"
        assert payload["journal_number"].startswith("JE-")


@pytest.mark.asyncio
async def test_agent_sees_unbalanced_rejection(monkeypatch) -> None:
    """Business-rule rejection (JE_UNBALANCED) reaches the LLM as a tool
    error instead of crashing the stream."""
    ids = await _bootstrap()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _login(client, ids["email"])

        mock = MockProvider(
            script=[
                AssistantMessage(
                    tool_calls=[
                        _tc(
                            "c1",
                            "create_journal_entry",
                            {
                                "journal_date": "2026-08-30",
                                "lines": [
                                    {
                                        "account_id": ids["cash_id"],
                                        "debit_amount": 100,
                                        "credit_amount": 0,
                                    },
                                    {
                                        "account_id": ids["revenue_id"],
                                        "debit_amount": 0,
                                        "credit_amount": 200,
                                    },
                                ],
                            },
                        )
                    ]
                ),
                AssistantMessage(content="That entry was unbalanced."),
            ]
        )

        import app.api.v1.ai_chat as ai_chat_module

        monkeypatch.setattr(ai_chat_module, "build_provider", lambda: mock)

        res = await client.post(
            "/api/v1/ai/chat",
            json={
                "messages": [
                    {"role": "user", "content": "Record an unbalanced entry"}
                ]
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        events = _parse_sse(res.text)

        tool_results = [e for e in events if e["event"] == "tool_result"]
        assert tool_results, events
        payload = json.loads(tool_results[0]["result"])
        assert "error" in payload
        assert payload["error"]["error_code"] == "JE_UNBALANCED"

        # Stream still ends with a final answer (graceful degradation).
        assert events[-1]["event"] == "final"


@pytest.mark.asyncio
async def test_chat_requires_auth() -> None:
    """Without a JWT the chat endpoint returns 401."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.post(
            "/api/v1/ai/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert res.status_code == 401
