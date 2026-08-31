"""
AI Chat API routes (Phase 4 — Gate 4.3).

Server-Sent Events streaming endpoint for the sidebar chat. Each
orchestrator event (assistant text, tool calls, tool results, final)
is streamed to the UI as it happens.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import run_conversation
from app.ai.providers import AIProviderError, build_provider
from app.api.deps import get_db_with_rls
from app.core.security import get_current_user

router = APIRouter(prefix="/ai", tags=["AI Assistant"])


class ChatMessage(BaseModel):
    """One message in the conversation history."""

    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    """Payload for POST /ai/chat."""

    messages: list[ChatMessage] = Field(min_length=1, max_length=50)


@router.get("/status")
async def ai_status() -> dict[str, Any]:
    """Report the configured AI mode so the UI can adapt (setup form
    vs. chat) without needing credentials."""
    from app.core.config import settings

    return {
        "module": "ai_assistant",
        "mode": str(settings.ai_mode),
        "provider_ready": settings.ai_mode != "disabled",
    }


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    current_user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """Stream a conversation as SSE events.

    Event format: ``data: {"event": "...", ...}\\n\\n`` — the frontend
    reads these incrementally to render tool-call chips and the final
    answer.
    """
    try:
        provider = build_provider()
    except AIProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if provider is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "AI_DISABLED",
                "message": (
                    "AI features are disabled. Set APEX_AI_MODE to byok "
                    "or local in the backend .env to enable the assistant."
                ),
            },
        )

    messages = [{"role": m.role, "content": m.content} for m in payload.messages]

    async def event_stream():
        try:
            async for event in run_conversation(
                provider, db, current_user, messages
            ):
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            await provider.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
