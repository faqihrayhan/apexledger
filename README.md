# ApexLedger

Open-core, on-premise accounting platform with a database-enforced double-entry
ledger engine. Local-first architecture: all financial data stays on your
machine, with business rules locked inside PostgreSQL.

## Overview

ApexLedger is designed for businesses that require full ownership of their
financial data. Instead of trusting an application layer to enforce accounting
integrity, every business rule — double-entry balance validation, journal
posting, reversals, and role-based access — is implemented as PL/pgSQL
functions and Row-Level Security (RLS) policies inside PostgreSQL. The API
layer stays thin, auditable, and stateless.

Core principles:

- **Local-first** — the database runs on the user's machine; no data leaves the host.
- **Database-enforced integrity** — unbalanced entries are rejected by the
  engine itself, not by frontend or API validation alone.
- **Immutable ledger** — posted entries cannot be edited or deleted;
  corrections are made through reversing entries.
- **Multi-entity by design** — strict tenant isolation through RLS plus
  application-level entity scoping (dual-layer defense).
- **AI-native** — pluggable assistant layer: bring your own API key, run a
  local model, or keep it fully disabled. Disabled by default.

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.0 (async), Alembic |
| Database | PostgreSQL 15 — RLS, PL/pgSQL RPCs, per-entity sequences |
| Auth | Local JWT, Argon2 password hashing |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS |
| Desktop | Tauri (planned) |
| Testing | pytest, pytest-asyncio, httpx, Ruff, ESLint, tsc |
| CI | GitHub Actions — ruff, pytest (PostgreSQL 15), eslint, tsc, vite build |

## Repository Structure

```text
apexledger/
├── backend/            # FastAPI service
│   ├── app/            # Application code (API, models, schemas, core)
│   ├── alembic/        # Migrations: schema + RLS + PL/pgSQL RPCs
│   ├── tests/          # 50-test suite (business-math assertions)
│   └── cli.py          # Backup / restore / update-check CLI
├── frontend/           # React + Vite + TypeScript client
├── website/            # Marketing site (static)
├── docs/               # Public project documentation
└── .github/            # CI workflow, issue & PR templates
```

## Modules

All modules below are implemented end-to-end (schema → RPC → API → tests):

| Module | Scope |
|---|---|
| GL & CoA | Double-entry engine, chart of accounts, posting/reversal, trial balance |
| System | Entity setup wizard, fiscal years & periods, user management |
| M2 — Payroll & Tax | BPJS components, official TER rates (PMK 168/2023), payroll runs |
| M3 — Inventory | Moving-average costing, BOM explosion, work orders, stock ledger |
| M3A — Production costing | Material + labor + overhead per work order |
| M4 — Sales & AR | Credit-limit gate, sales orders → delivery → AR invoices, PPN |
| M4A — Sales Return | Credit notes, stock back at cost basis, AR reduction |
| M5 — Procurement & AP | PR → PO → GRN 3-way match, dynamic approval engine (thresholds) |
| M5A — Purchase Return & Landed Cost | Debit notes, cost capitalization (qty/value/weight) |
| M6 — Treasury | Kasbon lifecycle, bank reconciliation auto-match, cash-flow forecast |
| M7 — Fixed Assets | Straight-line & declining balance, monthly batch via scheduler, disposal |
| M8 — Budgeting & Analytics | Budget lifecycle with audit snapshots, budget-vs-actual variance, trends, productivity metrics |

## Security Model

- **Row-Level Security** — every table scoped by `entity_id` with JWT-claim
  injection (`jwt.claims.*`), dual-layered with application-level checks.
- **Role checks hardened against NULL** — all 30 role-guarded RPCs reject
  requests when the role claim is missing entirely (no NULL-bypass);
  locked by dedicated regression tests.
- **Immutable audit** — budget revisions store before-snapshots; posted
  journals are irreversible.
- **Zero phone-home** — Community edition performs no outbound telemetry.

## Database & RPC Layer

Business rules live in 49 PL/pgSQL functions shipped via Alembic migrations.
Migrations create tables, RLS policies, and the RPCs in one transactional
chain — a fresh database reaches a fully-working state with
`alembic upgrade head`.

## API Surface

~60 REST endpoints under `/api/v1`, all authenticated, grouped by module.
Money amounts travel as strings (never floats); the engine itself
computes in `NUMERIC`/`Decimal`.

## Testing

- 50 pytest tests against a real PostgreSQL instance (recreated per session).
- Assertions verify exact business math (depreciation schedules, variance
  percentages, tax splits), not just status codes.
- Ruff (Python) and ESLint + tsc (frontend) gates in CI.

## Continuous Integration

`.github/workflows/ci.yml` runs on every push to `main` and on all pull
requests:

- **backend** — ruff + the full pytest suite against a PostgreSQL 15 service
  container.
- **frontend** — eslint, `tsc -b --noEmit`, and a production vite build.
- **readme-freshness** — fails the build when a push changes application code
  without updating `README.md` (escape hatch: `[skip-readme]` in the commit
  message).

## Frontend Coverage

Login/setup, dashboard, GL (journals, trial balance, chart of accounts), AI
chat, and all module UIs M2–M8: Payroll, Inventory (on-hand, master, movements,
work orders), Sales & AR (orders → delivery → invoice → payment, POS, returns),
Procurement (PO → approval → GRN inspection → 3-way match bills, returns,
landed costs), Treasury (kasbon lifecycle, bank master, reconciliation,
forecast), Fixed Assets (registration, depreciation batch, schedule, disposal),
and Budgeting (lifecycle with revisions, variance report, trend, productivity).

## Development

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Database (PostgreSQL 15 running on localhost:5432)
alembic upgrade head

# Run
uvicorn main:app --reload

# Tests / lint
python -m pytest tests/ -q
ruff check app tests cli.py

# Frontend
cd ../frontend
npm ci
npm run dev
```

## License

Open-core. Community edition is free for local deployment; enterprise
features (license-key activation) are optional.
