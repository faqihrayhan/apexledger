# Architecture

How the ApexLedger repository is laid out, and where everything lives.
Read this before navigating the codebase for the first time.

## Repository Layout

```text
apexledger/
├── backend/               # FastAPI service (Python 3.11)
│   ├── main.py            # ← THE entry point (uvicorn main:app) — NOT inside app/
│   ├── app/                # Application package (API, models, schemas, core)
│   │   ├── api/v1/         # Routers by module (gl, hr, sales, budgeting, …)
│   │   ├── models/         # SQLAlchemy ORM models
│   │   ├── schemas/        # Pydantic request/response schemas
│   │   ├── core/           # config, security, rpc_errors
│   │   ├── ai/             # AI providers + tool calling + orchestrator
│   │   ├── cron/           # APScheduler jobs (depreciation, update checks)
│   │   └── db/             # engine, session factory, base classes
│   ├── alembic/versions/   # 15 migrations: schema + RLS + 49 PL/pgSQL RPCs
│   ├── tests/              # 53-test suite (recreates apexledger_test DB)
│   ├── cli.py              # ops CLI: init/serve/backup/update/status/license
│   ├── init_db.py          # manual bootstrap helper (dev only)
│   └── pyproject.toml
├── frontend/               # React + Vite + TypeScript client
│   ├── src/pages/          # one file per module page (Payroll, Sales, …)
│   ├── src/App.tsx         # page switcher (Zustand store, no react-router)
│   ├── src/components/     # AppLayout, AiChat, ui primitives
│   ├── src/stores/         # Zustand: auth + ui (page navigation)
│   ├── src/lib/            # api client (JWT auto-inject), types, utils
│   └── src-tauri/          # Tauri v2 desktop config (Rust toolchain needed)
├── docs/                   # public project documentation
├── website/                # marketing site (static HTML/CSS)
└── .github/                # CI workflow, issue & PR templates
```

## Key Conventions

### Entry point

`backend/main.py` sits at the **root of `backend/`**, next to `app/`.
It is invoked as `uvicorn main:app` — **not** `app.main:app` (the
common FastAPI convention). This is the single most common navigation
mistake; agents and new contributors should check here first.

### Routing

The SPA uses a Zustand store (`frontend/src/stores/ui.ts`) with a `Page`
union type + a switch in `App.tsx` + nav items in `AppLayout.tsx`.
There is deliberately **no react-router**. Adding a page means touching
all three.

### Money

All amounts travel as **strings** in JSON (Decimal precision), and the
engine computes in `NUMERIC`. Never parse amounts as floats in TS.

### Server base URL (browser vs. desktop)

All API calls go through `api.ts`, which prefixes requests with
`apiBase()` from `stores/server.ts`. Empty base → same-origin (browser
mode via the Vite proxy); a persisted absolute URL → the Tauri desktop
app pointing at the factory server. The connect screen
(`pages/Connect.tsx`) probes `/system/status` before committing a URL.
The SSE stream in `AiChat.tsx` follows the same contract.

### Business rules

All accounting logic lives in PL/pgSQL RPCs (`fn_*`) created by Alembic
migrations. The FastAPI layer is a thin, stateless wrapper enforcing
auth + coarse role guards + entity scoping. When adding a module:
migration (tables + RLS + RPCs) → models → schemas → router → tests.

### Testing

`tests/conftest.py` drops/creates a dedicated `apexledger_test`
database per session, truncates between tests, and disposes engines.
Assertions verify exact business math, not just status codes.

### Documentation updates

**Rule: every new feature ships with a docs update.** If you add a
module, endpoint, CLI command, or env var, update the relevant file in
`docs/` in the same PR. `docs/SETUP.md` covers setup/env/CLI;
`docs/ARCHITECTURE.md` (this file) covers layout + conventions;
`README.md` is the entry point and must stay in sync (CI enforces
readme freshness for code changes).
