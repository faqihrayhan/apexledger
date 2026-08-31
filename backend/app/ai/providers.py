"""
AI provider wrappers (Phase 4 — Gate 4.1).

Unified interface for chat completion with tool calling across:
- OpenAI-compatible endpoints (OpenAI, Ollama `/v1`, LM Studio, vLLM...)
- Local Ollama native API

The interface is deliberately minimal: a ``chat`` method that accepts a
message list plus JSON-schema tool definitions and yields assistant
messages or tool calls. Providers are async and streaming-capable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import AIMode, settings

# ---------------------------------------------------------------------------
# Unified message/tool dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    """A single tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AssistantMessage:
    """One assistant turn: either text content and/or tool calls."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class ToolResult:
    """A tool execution outcome fed back to the LLM."""

    tool_call_id: str
    name: str
    result: str  # JSON-serialized result for the LLM
    is_error: bool = False


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------


class AIProvider:
    """Minimal async provider interface with tool-calling support."""

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantMessage:
        """Send one chat turn. Must be implemented by each provider."""
        raise NotImplementedError

    async def close(self) -> None:
        """Release the underlying HTTP client."""


# ---------------------------------------------------------------------------
# OpenAI-compatible provider (covers OpenAI + Ollama /v1 + vLLM + LM Studio)
# ---------------------------------------------------------------------------


class OpenAICompatProvider(AIProvider):
    """Any endpoint speaking the OpenAI chat-completions dialect.

    Tool calling follows the OpenAI format::

        tools=[{"type": "function", "function": {...}}]
        assistant message with tool_calls=[{"id": ..., "function": {...}}]
        user message with role="tool" and tool_call_id
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers=self._build_headers(),
        )

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantMessage:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
        }

        response = await self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]["message"]
        tool_calls: list[ToolCall] = []
        for tc in choice.get("tool_calls") or []:
            fn = tc["function"]
            try:
                args = json.loads(fn["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {"_raw": fn["arguments"]}
            tool_calls.append(
                ToolCall(id=tc["id"], name=fn["name"], arguments=args)
            )

        return AssistantMessage(
            content=choice.get("content"),
            tool_calls=tool_calls,
        )

    async def close(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------


class AIProviderError(RuntimeError):
    """Raised when the configured AI mode cannot produce a provider."""


def build_provider() -> AIProvider | None:
    """Instantiate the provider matching the configured AI mode.

    Returns None when AI is disabled. Raises AIProviderError when the
    mode requires credentials that are missing.
    """
    mode = settings.ai_mode

    if mode == AIMode.DISABLED:
        return None

    if mode == AIMode.BYOK:
        if not settings.ai_openai_api_key:
            raise AIProviderError(
                "AI mode is BYOK but APEX_AI_OPENAI_API_KEY is not set."
            )
        return OpenAICompatProvider(
            base_url=settings.ai_openai_base_url or "https://api.openai.com/v1",
            model="gpt-4o-mini",
            api_key=settings.ai_openai_api_key,
        )

    if mode == AIMode.LOCAL:
        return OpenAICompatProvider(
            base_url=f"{settings.ai_ollama_base_url.rstrip('/')}/v1",
            model=settings.ai_ollama_model,
            # Ollama's OpenAI-compat layer does not require an API key.
            api_key="ollama",
        )

    if mode == AIMode.TURNKEY:
        # Enterprise gateway — implemented with the license system (Phase 5).
        raise AIProviderError(
            "Turnkey AI gateway is an Enterprise feature (Phase 5)."
        )

    return None
