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
- **AI-ready** — pluggable assistant layer (BYOK API keys or local models)
  planned for the desktop client.

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.0 (async), Alembic |
| Database | PostgreSQL 15 — RLS, PL/pgSQL RPCs, per-entity sequences |
| Auth | Local JWT, Argon2 password hashing |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS |
| Desktop | Tauri (planned) |
| Testing | pytest, pytest-asyncio, httpx |

## Repository Structure

```
apexledger/
├── backend/
│   ├── app/
│   │   ├── api/v1/        # REST routers (auth, gl, coa, system, ai)
│   │   ├── core/          # Config, security, RPC error mapping
│   │   ├── db/            # Async engine, session, RLS context injection
│   │   ├── models/        # SQLAlchemy ORM models
│   │   └── schemas/       # Pydantic request/response schemas
│   ├── alembic/versions/  # Migrations: DDL, RLS policies, RPCs, seeds
│   └── tests/            # Integration tests (isolated test database)
└── frontend/              # React + Vite + Tailwind (dark UI)
```

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+ (frontend)
- Docker (for the PostgreSQL container)

### 1. Database

Start a local PostgreSQL 15 container:

```bash
docker run -d --name apexledger-db \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=apexledger \
  -p 5432:5432 postgres:15
```

### 2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # edit credentials as needed
alembic upgrade head       # apply schema, RLS, and RPC migrations
uvicorn main:app --reload  # API at http://localhost:8000/docs
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

### First Boot

The instance initializes through a one-time setup wizard instead of manual
SQL. Call `POST /api/v1/system/setup` once to create the entity, the first
administrator, the fiscal year, and its twelve monthly periods in a single
atomic transaction. Subsequent calls are rejected with HTTP 409.

## API Overview

Interactive documentation is served at `/docs` (Swagger) and `/redoc`.

| Endpoint | Description |
|---|---|
| `POST /api/v1/auth/register` | Register a user profile |
| `POST /api/v1/auth/login` | Obtain a JWT access token |
| `GET /api/v1/auth/me` | Current user claims |
| `GET /api/v1/system/status` | Instance initialization state |
| `POST /api/v1/system/setup` | One-time first-boot wizard (entity, admin, fiscal year) |
| `POST /api/v1/gl/journals` | Create a draft journal entry (double-entry validated) |
| `GET /api/v1/gl/journals` | List journal entries (entity-scoped) |
| `POST /api/v1/gl/journals/{id}/post` | Post a draft entry (DRAFT to POSTED) |
| `POST /api/v1/gl/journals/{id}/reverse` | Reverse a posted entry (creates mirror entry) |
| `GET /api/v1/gl/accounts` | List chart of accounts |
| `POST /api/v1/gl/accounts` | Create an account (finance roles only) |
| `PATCH /api/v1/gl/accounts/{id}` | Update an account (code and type immutable) |
| `DELETE /api/v1/gl/accounts/{id}` | Deactivate (soft) or delete unused (hard) |
| `GET /api/v1/gl/reports/trial-balance` | Trial balance with debit/credit proof totals |

### Error Contract

Business-rule violations raised by database functions surface as structured
errors:

```json
{
  "detail": {
    "error_code": "JE_UNBALANCED",
    "message": "Total debit must equal total credit."
  }
}
```

Common codes map to HTTP status codes: `UNAUTHENTICATED` to 401,
`FORBIDDEN_ROLE`/`FORBIDDEN_ENTITY` to 403, and rule violations such as
`JE_UNBALANCED`, `PERIOD_CLOSED`, or `ACCOUNT_NOT_POSTABLE` to 422.

## Security Model

- **Row-Level Security** — every table is entity-scoped. Policies compare
  `app.current_entity_id` (injected from JWT claims by the API layer) against
  the row's entity.
- **Immutable ledger** — `UPDATE` and `DELETE` privileges on journal tables are
  revoked at the database level.
- **Dual-layer defense** — read endpoints additionally filter by the caller's
  entity at the application level, so isolation holds even if the connection
  role bypasses RLS.
- **Role enforcement in the engine** — journal creation, posting, and
  reversal check the caller's role inside the database function, not only in
  the API.

## Testing

The test suite runs against a dedicated `apexledger_test` database that is
recreated per session, keeping runs idempotent and isolated:

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
ruff check app tests
```

Coverage includes the full journal lifecycle (create, post, reverse),
balance validation, entity isolation across tenants, role guards, the setup
wizard, and the trial balance mathematical proof (grand debit equals grand
credit).

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Architecture and foundation (schema, auth, RLS, setup wizard) | Complete |
| 2 | Core accounting engine (journal RPCs, chart of accounts, trial balance) | Complete |
| 3 | Accounts payable / receivable, inventory, payroll modules | Planned |
| 4 | Desktop client (Tauri), AI assistant sidebar | Planned |
| 5 | Multi-company consolidation, reporting suite | Planned |

## License

To be announced. The core platform is intended to be released under an
open-source license; see LICENSE before redistributing.
