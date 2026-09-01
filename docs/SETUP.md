# Setup Guide

Complete local setup for ApexLedger — backend (FastAPI + PostgreSQL),
frontend (React + Vite), and operational tooling.

> **Where is `main.py`?** The FastAPI entry point is
> `backend/main.py` — at the **root of the `backend/` folder**, next to
> `app/`, **not** inside `app/`. All `uvicorn`, `pytest`, and `alembic`
> commands below must run from `backend/`.

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | backend runtime |
| Node.js | 22 LTS | frontend build |
| PostgreSQL | 15 | via Docker (recommended) or a local install |
| Docker | any recent | only if using the managed container |

## 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Database

Option A — managed Docker container (matches `cli.py init`):

```bash
docker run -d --name apexledger-db \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=apexledger \
  -p 5432:5432 postgres:15
```

Option B — any PostgreSQL 15 reachable at `localhost:5432`
(user `postgres`, password `postgres`, database `apexledger`),
or override via `APEX_DATABASE_URL` (see env vars below).

### Migrations

```bash
# from backend/ — creates every table, RLS policy, and all 49 RPCs
alembic upgrade head
```

### Run the API server

```bash
# from backend/ — note: main:app, NOT app.main:app
uvicorn main:app --reload
```

The API is now at `http://localhost:8000` (docs at `/docs`).
On first boot the frontend shows the setup wizard which creates the
entity, admin user, and fiscal year.

## 2. Frontend

```bash
cd frontend
npm ci
npm run dev      # dev server with HMR
```

Production build:

```bash
npm run build    # outputs to frontend/dist/
```

## Environment Variables

All settings are optional with sane defaults, prefix `APEX_`, read from
`backend/.env` or the process environment:

| Variable | Default | Purpose |
|---|---|---|
| `APEX_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/apexledger` | Async SQLAlchemy DSN |
| `APEX_JWT_SECRET` | `CHANGE-ME-IN-PRODUCTION` | JWT signing secret — **must** be changed outside dev |
| `APEX_AI_MODE` | `DISABLED` | `DISABLED` / `BYOK` (OpenAI-compatible key) / `LOCAL` (Ollama) |
| `APEX_AI_OPENAI_API_KEY` | — | OpenAI-compatible API key (BYOK) |
| `APEX_AI_OPENAI_BASE_URL` | — | Override base URL (vLLM, LM Studio, proxies) |
| `APEX_AI_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint (LOCAL) |
| `APEX_AI_OLLAMA_MODEL` | `llama3.1` | Ollama model name (LOCAL) |
| `APEX_UPDATE_CHECK_ENABLED` | `true` | Opt-in update checker |

## CLI (operations)

From `backend/` with the venv active:

```bash
python cli.py init      # start container + wait ready + run migrations
python cli.py serve     # run the API server (wraps uvicorn)
python cli.py backup    # pg_dump -> backups/apexledger-<ts>.sql.gz
python cli.py update    # check for updates (opt-in, no forced upgrade)
python cli.py status    # container + migration health overview
python cli.py license   # show license status (Community: no key needed)
```

## Tests & Lint

```bash
# from backend/ — the venv must be on PATH so conftest can call alembic
PATH="$PWD/.venv/bin:$PATH" python -m pytest -q
ruff check app tests cli.py

# from frontend/
npx eslint src
npx tsc -b --noEmit
npm run build
```

The test suite recreates a dedicated `apexledger_test` database per
session and truncates per test — it never touches your dev data.

## Desktop App (Tauri)

`frontend/src-tauri/` holds the Tauri v2 configuration. Building the
desktop bundle requires the Rust toolchain (`rustup`); see
`frontend/src-tauri/README.md` once the toolchain is installed.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `uvicorn: error: No module named 'app.main'` | Wrong module path | Run `uvicorn main:app` from `backend/` |
| `PERIOD_NOT_FOUND` on new transactions | Fiscal periods expired (dev DB was seeded for an earlier year) | Create a new fiscal year + periods, or re-init |
| RPC behaves stale after editing an applied migration | Migration file edited post-apply | `alembic downgrade <prev> && alembic upgrade head` |
| pytest can't find `alembic` binary | venv not on PATH | `PATH="$PWD/.venv/bin:$PATH" python -m pytest` |
| CI backend install fails on hatchling | Packaging config drift | Verify `pyproject.toml` has `[tool.hatch.build.targets.wheel] packages = ["app"]` and no missing `readme` path |
