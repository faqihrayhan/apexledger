"""
AI orchestrator — routes prompts to tool calls (Phase 4 — Gate 4.3).

The conversation loop:
1. User prompt + system prompt -> LLM (with JSON Schema tools).
2. LLM answers directly OR requests tool calls.
3. Tools execute against the DB inside the caller's security context.
4. Tool results are fed back to the LLM.
5. Repeat until a final text answer or the iteration cap is reached.

Events are yielded so the API layer can stream progress (tool calls,
results, and the final answer) to the UI sidebar via SSE.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import AIProvider
from app.ai.tools import TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger("apexledger.ai")

MAX_TOOL_ITERATIONS = 5

SYSTEM_PROMPT = (
    "You are ApexLedger, an accounting assistant embedded in an "
    "on-premise double-entry accounting platform. You help the user "
    "record transactions, review journals, and read reports.\n\n"
    "Rules:\n"
    "- Amounts are strings of decimal numbers; keep full precision.\n"
    "- Journal entries are created as DRAFT; only post when the user "
    "explicitly asks to post.\n"
    "- Always call list_accounts first when you need account ids.\n"
    "- Every journal must balance: total debit == total credit.\n"
    "- Answer concisely; show numbers with thousand separators."
)


async def run_conversation(
    provider: AIProvider,
    db: AsyncSession,
    current_user: dict[str, Any],
    user_messages: list[dict[str, Any]],
    max_iterations: int = MAX_TOOL_ITERATIONS,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run one agent conversation, yielding progress events.

    Event shapes (all JSON-serializable dicts with an ``event`` key):
    - {"event": "assistant", "content": str}
    - {"event": "tool_call", "name": str, "arguments": dict}
    - {"event": "tool_result", "name": str, "result": str, "is_error": bool}
    - {"event": "final", "content": str}
    - {"event": "error", "message": str}
    """
    # Seed the conversation with the system prompt + user history.
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *user_messages,
    ]

    for _iteration in range(max_iterations):
        assistant = await provider.chat(messages, TOOL_DEFINITIONS)

        # No tool calls -> final answer.
        if not assistant.tool_calls:
            final_text = assistant.content or ""
            if final_text:
                yield {"event": "assistant", "content": final_text}
            yield {"event": "final", "content": final_text}
            return

        # Text alongside tool calls is progress commentary; stream it too.
        if assistant.content:
            yield {"event": "assistant", "content": assistant.content}

        # Append the assistant turn (with tool calls) to history.
        messages.append(
            {
                "role": "assistant",
                "content": assistant.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in assistant.tool_calls
                ],
            }
        )

        # Execute each requested tool and feed results back.
        for tc in assistant.tool_calls:
            yield {"event": "tool_call", "name": tc.name, "arguments": tc.arguments}

            result_json = await execute_tool(db, tc.name, tc.arguments, current_user)
            is_error = '"error"' in result_json[:64]

            yield {
                "event": "tool_result",
                "name": tc.name,
                "result": result_json,
                "is_error": is_error,
            }

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_json,
                }
            )

    # Iteration cap reached without a final answer.
    yield {
        "event": "error",
        "message": (
            f"Reached the maximum of {max_iterations} tool iterations "
            "without a final answer."
        ),
    }
