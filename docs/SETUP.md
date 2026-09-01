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
entity, admin user, and fiscal year — see "First-Boot Setup" below.

### First-Boot Setup (the setup wizard)

A fresh database serves `is_initialized: false` from
`GET /api/v1/system/status`; the frontend automatically swaps the
login form for the **Setup Wizard**. Fill in:

| Field | Meaning | Constraints |
|---|---|---|
| Entity code / name | your company identity | code 2–20 chars, unique |
| Base currency | default ledger currency | default `IDR` |
| Admin full name / email / password | the first user | password ≥ 8 chars |
| Fiscal year | e.g. `2026` | 2000–2100 |

`POST /api/v1/system/setup` runs **one atomic transaction**: entity +
SUPER_ADMIN user + fiscal year + 12 monthly periods + audit entry,
and returns the first `access_token` — you land straight in the app.

Setup is once-only; a second call is rejected by the engine.

### Adding users

Users are created via `POST /api/v1/auth/register` (authenticated).
Once the instance is initialized, `entity_id` is required on the
payload. Pick one of the nine roles — see `docs/USER_FLOWS.md` →
Role Reference for what each role may do. All role checks are
enforced twice: coarse guards at the API layer and NULL-hardened
checks inside the PL/pgSQL RPCs.

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

### AI modes (right sidebar)

The AI assistant is disabled by default and never phones home. Set
`APEX_AI_MODE` to enable it:

| Mode | What it does | Required env |
|---|---|---|
| `DISABLED` (default) | sidebar shows a hint, no calls are made | — |
| `BYOK` | bring your own OpenAI-compatible API key | `APEX_AI_OPENAI_API_KEY` (optionally `..._BASE_URL` for vLLM / LM Studio / proxies) |
| `LOCAL` | runs against a local Ollama instance | `APEX_AI_OLLAMA_BASE_URL` (default `http://localhost:11434`) + `APEX_AI_OLLAMA_MODEL` |

The assistant can list accounts and journals, create/post journal
entries, and pull trial balances through JSON-Schema tool calling
routed to the same RPCs — subject to the logged-in user's role and
entity scoping.

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

## Quick Install (one line)

The fastest way to get a working ApexLedger server:

```bash
curl -fsSL https://raw.githubusercontent.com/faqihrayhan/apexledger/main/install.sh | bash
```

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/faqihrayhan/apexledger/main/install.ps1 | iex
```

The installer clones the repo to `~/apexledger`, creates the Python venv,
installs the backend, and runs `apexledger init` (Postgres container +
database + migrations — zero manual SQL). Then start the server:

```bash
~/apexledger/backend/.venv/bin/python cli.py serve
# → http://localhost:8000 (setup wizard on first visit)
```

Requirements: `git`, Python 3.11+, and Docker (runs the database).
Re-running the installer is safe — every step is idempotent, an existing
checkout is updated in place. Environment overrides: `REPO_URL`,
`INSTALL_DIR`, `BRANCH`.

The sections below are the **manual / advanced** path (no Docker, custom
Postgres, custom ports) — most users never need them.

## Desktop App (Tauri)

`frontend/src-tauri/` holds the Tauri v2 shell. Installers are built for
all platforms — Windows `.msi` + `.exe` (NSIS), macOS `.dmg`, Linux
`.AppImage`. Two ways to build them:

**A. GitHub Actions (recommended — no local Rust needed).** Repo →
Actions → *Desktop Build (Tauri)* → *Run workflow*. Pick `all` to build
every platform (Windows `.msi` + `.exe`, macOS `.dmg`, Linux
`.AppImage`); `windows` (default) keeps the run cheap. Installers are
attached to the run as artifacts (14 days).

**B. Locally.** Install the Rust toolchain (`rustup`) plus the platform
extras (Linux also needs `libwebkit2gtk-4.1-dev`), then:

```bash
cd frontend
npm ci
npm run tauri build
# → src-tauri/target/release/bundle/{msi,dmg,appimage}/
```

**First launch (desktop):** the app shows a *Connect to server* screen —
enter the factory server address (e.g. `http://192.168.1.100:8000`).
The choice is persisted (`apexledger-server` in localStorage) and can be
changed later via the header chip. The backend must listen on the LAN
interface (`uvicorn main:app --host 0.0.0.0`) for remote desktop clients
to reach it.

## Docker Quickstart (full stack in 3 commands)

```bash
# 1. database
docker run -d --name apexledger-db \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=apexledger \
  -p 5432:5432 postgres:15

# 2. backend (from backend/)
cd backend && pip install -e ".[dev]" && alembic upgrade head
uvicorn main:app --reload

# 3. frontend (from frontend/, second terminal)
npm ci && npm run dev
```

Open the URL Vite prints (default `http://localhost:5173`) → the
setup wizard appears → fill it once → you're in.

## Demo Walkthrough (10 minutes)

After the setup wizard, exercise every core loop:

1. **GL** — Accounts → add a few accounts (4000 Revenue, 5000 Expense,
   1000 Cash, 2100 AP). New Journal → 2 balanced lines → Post.
   Trial Balance → grand totals match.
2. **Procurement** — Vendors → add one. Purchase order → add a line →
   Submit (note the required approval role from the threshold
   engine) → Approve → Receive → Inspect (accept all) → Bills →
   create + Match → Payments → pay it.
3. **Sales** — Customers → add one (credit limit 20000000). Sales
   order → Confirm → Deliver → Invoice → Payment → paid.
4. **Inventory** — check On-Hand: the received stock and the
   delivered stock netted out at cost.
5. **Payroll** — Employees → add one → Periods → create this month →
   Calculate → Approve (pick AP Gaji account) → Disburse (pick cash
   account).
6. **Assets** — register a laptop (36-month SL) → run one
   depreciation batch → Schedule shows the rows.
7. **Budgeting** — create a budget with a few lines → Approve →
   Vs-actual at month 12 → Trend REVENUE.
8. **AI (optional)** — set `APEX_AI_MODE=BYOK` + key, restart, then
   ask the sidebar: "create a balanced journal for 500000 from Cash
   to Revenue and post it".

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `uvicorn: error: No module named 'app.main'` | Wrong module path | Run `uvicorn main:app` from `backend/` |
| `PERIOD_NOT_FOUND` on new transactions | Fiscal periods expired (dev DB was seeded for an earlier year) | Create a new fiscal year + periods, or re-init |
| RPC behaves stale after editing an applied migration | Migration file edited post-apply | `alembic downgrade <prev> && alembic upgrade head` |
| pytest can't find `alembic` binary | venv not on PATH | `PATH="$PWD/.venv/bin:$PATH" python -m pytest` |
| CI backend install fails on hatchling | Packaging config drift | Verify `pyproject.toml` has `[tool.hatch.build.targets.wheel] packages = ["app"]` and no missing `readme` path |
