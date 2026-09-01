# Configuration

Everything ApexLedger needs to run is optional with sane defaults. All settings use the `APEX_` prefix and are read from `backend/.env` or the process environment — there is no config file to hand-edit, no service to restart beyond the API server.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `APEX_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/apexledger` | Async SQLAlchemy DSN — point it at your Postgres |
| `APEX_JWT_SECRET` | `CHANGE-ME-IN-PRODUCTION` | JWT signing secret — **must** be changed outside dev |
| `APEX_AI_MODE` | `DISABLED` | `DISABLED` / `BYOK` / `LOCAL` — see below |
| `APEX_AI_OPENAI_API_KEY` | — | OpenAI-compatible API key (BYOK mode) |
| `APEX_AI_OPENAI_BASE_URL` | — | Override base URL — vLLM, LM Studio, proxies |
| `APEX_AI_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint (LOCAL mode) |
| `APEX_AI_OLLAMA_MODEL` | `llama3.1` | Ollama model name (LOCAL mode) |
| `APEX_UPDATE_CHECK_ENABLED` | `true` | Opt-in update checker |

A minimal production `.env`:

```bash
APEX_DATABASE_URL=postgresql+asyncpg://apex:strong-password@localhost:5432/apexledger
APEX_JWT_SECRET=<long random string>
```

That is genuinely all — the AI features stay off, the ledger works.

## AI modes (right sidebar)

The AI assistant is disabled by default and **never phones home**. When you want it, pick one of three modes:

| Mode | What it does | Required env |
|---|---|---|
| `DISABLED` (default) | sidebar shows a hint, no calls are made | — |
| `BYOK` | bring your own OpenAI-compatible API key | `APEX_AI_OPENAI_API_KEY` (optionally `APEX_AI_OPENAI_BASE_URL` for vLLM / LM Studio / proxies) |
| `LOCAL` | runs against a local Ollama instance | `APEX_AI_OLLAMA_BASE_URL` + `APEX_AI_OLLAMA_MODEL` |

### What the assistant can do

When enabled, the assistant lives in the right sidebar and can:

- **list** accounts and journals,
- **create and post** journal entries,
- **pull** trial balances,

all through JSON-Schema tool calling routed to the **same RPCs** the UI uses — which means two things:

1. it is subject to the **logged-in user's role** — an operator's assistant can never do what the operator cannot;
2. it is scoped to the **same entity** as the session — no cross-company leaks.

It cannot bypass validation: an unbalanced AI-created journal is rejected by `JE_UNBALANCED` just like a human one.

### BYOK example

```bash
APEX_AI_MODE=BYOK
APEX_AI_OPENAI_API_KEY=sk-...
# optional — point at vLLM / LM Studio / a proxy instead of OpenAI:
# APEX_AI_OPENAI_BASE_URL=http://localhost:8001/v1
```

### LOCAL example

```bash
APEX_AI_MODE=LOCAL
APEX_AI_OLLAMA_BASE_URL=http://localhost:11434
APEX_AI_OLLAMA_MODEL=llama3.1
```

## Changing values

- Edit `backend/.env` and restart the API server (`cli.py serve` or `uvicorn main:app`) — that is the whole procedure.
- The JWT secret can be rotated; users just log in again.
- `APEX_DATABASE_URL` is the only variable that must be right before `alembic upgrade head`.

## What's next

- [CLI Reference](/docs/cli) — the six operational commands (init, serve, backup, …).
- [Installation](/docs/installation) — where these variables first come into play.
- For the RPC-level detail behind the AI's tool calls, see `docs/ARCHITECTURE.md` in the repository.
