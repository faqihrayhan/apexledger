"""
AI tool definitions mapped to PL/pgSQL RPCs (Phase 4 — Gate 4.2).

Each accounting RPC is exposed as a JSON Schema "tool" that the LLM
can invoke via function/tool calling. Tool execution runs against the
database with the caller's JWT context injected (RLS stays enforced),
so an AI agent can never escape the caller's entity or permissions.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rpc_errors import raise_from_rpc

# ---------------------------------------------------------------------------
# Tool JSON-schema definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_accounts",
            "description": (
                "List the chart of accounts for the current entity. Use this "
                "first to resolve account names to their ids before creating "
                "journal entries."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_journal_entry",
            "description": (
                "Create a double-entry journal entry (saved as DRAFT). The "
                "engine requires total debit to equal total credit and at "
                "least two lines. Amounts are plain numbers in the entity's "
                "base currency."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "journal_date": {
                        "type": "string",
                        "format": "date",
                        "description": "Posting date, e.g. 2026-08-30.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional memo for the whole entry.",
                    },
                    "lines": {
                        "type": "array",
                        "minItems": 2,
                        "description": "Debit/credit lines.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "account_id": {
                                    "type": "string",
                                    "format": "uuid",
                                    "description": "Account id from list_accounts.",
                                },
                                "debit_amount": {
                                    "type": "number",
                                    "minimum": 0,
                                    "description": "Debit amount (0 if crediting).",
                                },
                                "credit_amount": {
                                    "type": "number",
                                    "minimum": 0,
                                    "description": "Credit amount (0 if debiting).",
                                },
                                "description": {
                                    "type": "string",
                                    "description": "Optional line memo.",
                                },
                            },
                            "required": ["account_id", "debit_amount", "credit_amount"],
                        },
                    },
                },
                "required": ["journal_date", "lines"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "post_journal_entry",
            "description": (
                "Post a DRAFT journal entry, making it permanent and "
                "immutable. Requires the journal entry id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "journal_entry_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "The DRAFT entry id to post.",
                    },
                },
                "required": ["journal_entry_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trial_balance",
            "description": (
                "Get the trial balance report as of a date: per-account "
                "debit/credit totals with the grand-total balance proof."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "as_of": {
                        "type": "string",
                        "format": "date",
                        "description": "Cutoff date, e.g. 2026-12-31.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_journals",
            "description": (
                "List recent journal entries with status and totals. Useful "
                "for reviewing activity before summarizing or posting."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Max entries to return (default 20).",
                    },
                },
                "required": [],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool executors — thin wrappers over the same RPCs the REST API uses
# ---------------------------------------------------------------------------


def _dec(value: Any) -> str:
    """Serialize a Decimal amount as a fixed-precision string.

    Uses format 'f' (never scientific notation like 5E+5) so both LLMs
    and humans read clean amounts.
    """
    dec = Decimal(str(value))
    formatted = format(dec, "f")
    # Trim trailing zeros but keep at least one decimal digit stable:
    # 500000.00 -> 500000, 0.50 -> 0.5
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted or "0"


async def _list_accounts(db: AsyncSession, args: dict[str, Any]) -> str:
    # App-level entity filter is mandatory: the service connection is a
    # superuser, which bypasses RLS (dual-layer defense rule).
    rows = await db.execute(
        text(
            "SELECT id, account_code, account_name, account_type::text, "
            "normal_balance::text, is_postable "
            "FROM chart_of_accounts "
            "WHERE is_active = true AND entity_id = CAST(:eid AS uuid) "
            "ORDER BY account_code"
        ),
        {"eid": args["_entity_id"]},
    )
    accounts = [
        {
            "id": str(r[0]),
            "code": r[1],
            "name": r[2],
            "type": r[3],
            "normal_balance": r[4],
            "postable": r[5],
        }
        for r in rows.all()
    ]
    return json.dumps({"accounts": accounts})


def _parse_rpc_json(raw: object) -> dict[str, Any]:
    """Decode an RPC JSONB result (string or pre-decoded object)."""
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)  # type: ignore[arg-type]


async def _create_journal_entry(db: AsyncSession, args: dict[str, Any]) -> str:
    # RPC signature: fn_create_journal_entry(entity_id, jdate, descr, ccy, lines)
    # Amounts are serialized as strings (Decimal precision, JSONB-safe).
    journal_date = args["journal_date"]
    if isinstance(journal_date, str):
        journal_date = date.fromisoformat(journal_date)

    lines_json = json.dumps(
        [
            {
                "account_id": line["account_id"],
                "debit_amount": str(line.get("debit_amount", 0)),
                "credit_amount": str(line.get("credit_amount", 0)),
                "description": line.get("description"),
            }
            for line in args["lines"]
        ]
    )

    result = await db.execute(
        text(
            "SELECT fn_create_journal_entry("
            "  CAST(:entity_id AS uuid), CAST(:jdate AS date),"
            "  :descr, :ccy, CAST(:lines AS jsonb)"
            ") AS rpc"
        ),
        {
            "entity_id": args["_entity_id"],
            "jdate": journal_date,
            "descr": args.get("description"),
            "ccy": "IDR",
            "lines": lines_json,
        },
    )
    rpc = _parse_rpc_json(result.scalar_one())
    # fn_create_journal_entry returns {success, journal_entry_id, journal_number};
    # the entry is always created as DRAFT, so 'status' is not in the payload.
    return json.dumps(
        {
            "journal_entry_id": str(rpc["journal_entry_id"]),
            "journal_number": rpc["journal_number"],
            "status": "DRAFT",
        }
    )


async def _post_journal_entry(db: AsyncSession, args: dict[str, Any]) -> str:
    # RPC signature: fn_post_journal_entry(journal_entry_id)
    # Entity scoping is enforced inside the RPC via fn_current_entity_id().
    result = await db.execute(
        text("SELECT fn_post_journal_entry(CAST(:je_id AS uuid)) AS rpc"),
        {"je_id": args["journal_entry_id"]},
    )
    rpc = _parse_rpc_json(result.scalar_one())
    return json.dumps(
        {
            "journal_entry_id": str(rpc["journal_entry_id"]),
            "status": rpc["status"],
            "debit_total": str(rpc["debit_total"]),
            "credit_total": str(rpc["credit_total"]),
        }
    )


async def _get_trial_balance(db: AsyncSession, args: dict[str, Any]) -> str:
    as_of = args.get("as_of")
    if isinstance(as_of, str):
        as_of = date.fromisoformat(as_of)
    result = await db.execute(
        text(
            "SELECT * FROM fn_trial_balance("
            "  CAST(:eid AS uuid), CAST(:as_of_date AS date)"
            ") ORDER BY account_code"
        ),
        {"eid": args["_entity_id"], "as_of_date": as_of},
    )
    rows = result.mappings().all()

    # Grand-total balance proof: sum of net debits == sum of net credits.
    total_net_debit = sum((Decimal(str(r["net_debit"])) for r in rows), Decimal(0))
    total_net_credit = sum((Decimal(str(r["net_credit"])) for r in rows), Decimal(0))

    return json.dumps(
        {
            "rows": [
                {
                    "code": r["account_code"],
                    "name": r["account_name"],
                    "net_debit": _dec(r["net_debit"]),
                    "net_credit": _dec(r["net_credit"]),
                }
                for r in rows
            ],
            "grand_net_debit": str(total_net_debit),
            "grand_net_credit": str(total_net_credit),
            "is_balanced": total_net_debit == total_net_credit,
        }
    )


async def _list_journals(db: AsyncSession, args: dict[str, Any]) -> str:
    limit = int(args.get("limit", 20))
    rows = await db.execute(
        text(
            "SELECT je.id, je.journal_number, je.journal_date, "
            "je.description, je.status::text, "
            "COALESCE(SUM(GREATEST(jl.debit_amount, jl.credit_amount)), 0) "
            "AS total_amount "
            "FROM journal_entries je "
            "JOIN journal_lines jl ON jl.journal_entry_id = je.id "
            "WHERE je.entity_id = CAST(:p_entity_id AS uuid) "
            "GROUP BY je.id ORDER BY je.journal_date DESC, je.journal_number "
            "LIMIT :p_limit"
        ),
        {"p_entity_id": args["_entity_id"], "p_limit": limit},
    )
    journals = [
        {
            "id": str(r[0]),
            "number": r[1],
            "date": r[2].isoformat(),
            "description": r[3],
            "status": r[4],
            "total_amount": _dec(r[5]),
        }
        for r in rows.all()
    ]
    return json.dumps({"journals": journals})


TOOL_EXECUTORS = {
    "list_accounts": _list_accounts,
    "create_journal_entry": _create_journal_entry,
    "post_journal_entry": _post_journal_entry,
    "get_trial_balance": _get_trial_balance,
    "list_journals": _list_journals,
}


async def execute_tool(
    db: AsyncSession,
    name: str,
    arguments: dict[str, Any],
    current_user: dict[str, Any],
) -> str:
    """Execute an AI-requested tool inside the caller's security context.

    ``_entity_id`` / ``_user_id`` are injected server-side from the JWT
    (never from LLM arguments) so the agent cannot act on another
    tenant or impersonate a user. RLS remains active on the session.
    """
    executor = TOOL_EXECUTORS.get(name)
    if executor is None:
        return json.dumps({"error": f"Unknown tool: {name}"})

    args = {
        **arguments,
        "_entity_id": current_user["entity_id"],
        "_user_id": current_user["user_id"],
    }

    try:
        return await executor(db, args)
    except Exception as exc:
        # Surface business-rule rejections (P0001) as structured tool errors.
        try:
            raise raise_from_rpc(exc) from exc
        except Exception as http_exc:
            detail = getattr(http_exc, "detail", None)
            if isinstance(detail, dict):
                return json.dumps({"error": detail})
            return json.dumps({"error": str(http_exc)})
