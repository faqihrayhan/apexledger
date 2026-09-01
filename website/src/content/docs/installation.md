# Installation

ApexLedger runs entirely on one machine — PostgreSQL, the API server, and the UI. This page covers every way to install it: a one-line installer, a manual setup, Docker, and the desktop app for employees.

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Git | any recent | cloning the repository |
| Python | 3.11+ | runs the backend and the CLI |
| Docker | any recent | runs the PostgreSQL database (quick path) |
| Node.js | 20+ | only for frontend development |

The server machine (Linux / macOS / WSL) hosts everything. Employees connect from a desktop app or a browser — they install nothing but the app itself.

## Three ways to run it

| Mode | Best for | What you install |
|---|---|---|
| **Quick install** | trying it out fast, single-server deployments | one line of terminal |
| **Manual setup** | custom Postgres, no Docker, custom ports | git + Python + Docker, step by step |
| **Desktop app** | employees on Windows / macOS / Linux | a prebuilt installer from GitHub Releases |

## Quick install (one line)

Linux / macOS / WSL:

```bash
curl -fsSL https://raw.githubusercontent.com/faqihrayhan/apexledger/main/install.sh | bash
```

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/faqihrayhan/apexledger/main/install.ps1 | iex
```

### What the installer does

1. Clones the repository to `~/apexledger` (existing checkouts are updated in place).
2. Creates the Python virtual environment and installs the backend.
3. Runs `cli.py init` — starts the Postgres container, waits until it is ready, and applies all migrations. Zero manual SQL.
4. Prints the command to start the server.

Then start the API server:

```bash
~/apexledger/backend/.venv/bin/python cli.py serve
# → http://localhost:8000 — the setup wizard appears on first visit
```

The installer is **idempotent** — safe to re-run. Useful environment overrides: `REPO_URL`, `INSTALL_DIR`, `BRANCH`.

## Manual setup

The path for custom environments — existing PostgreSQL instance, no Docker, custom ports.

**1. Database** — either start the managed container (matches what `cli.py init` does):

```bash
docker run -d --name apexledger-db \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=apexledger \
  -p 5432:5432 postgres:15
```

…or point `APEX_DATABASE_URL` at any reachable PostgreSQL 15+ instance.

**2. Backend** — from `backend/`:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
alembic upgrade head     # creates every table, RLS policy, and all 49 RPCs
```

**3. API server** — note the module path, `main:app` (not `app.main:app`):

```bash
uvicorn main:app --reload
```

The API listens on `http://localhost:8000`, interactive docs at `/docs`.

**4. Frontend (development only)** — from `frontend/`:

```bash
npm ci
npm run dev             # dev server with HMR, prints a localhost URL
```

Production build: `npm run build` (outputs to `frontend/dist/`).

## Desktop app (for employees)

Prebuilt installers live on GitHub Releases:

| Platform | File |
|---|---|
| Windows | `.exe` (NSIS) or `.msi` |
| macOS | `.dmg` (Intel + Apple Silicon) |
| Linux | `.AppImage` |

On first launch the app shows a *Connect to server* screen — enter your server address (e.g. `http://192.168.1.100:8000`). The choice is persisted and can be changed later from the header chip.

For the desktop app to reach the server across the LAN, the backend must listen on the LAN interface:

```bash
uvicorn main:app --host 0.0.0.0
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `uvicorn: error: No module named 'app.main'` | wrong module path | run `uvicorn main:app` from `backend/` |
| `PERIOD_NOT_FOUND` on new transactions | fiscal periods were seeded for an earlier year | create a new fiscal year + periods, or re-init |
| RPC behaves stale after editing an applied migration | migration file edited post-apply | `alembic downgrade <prev> && alembic upgrade head` |
| pytest can't find the `alembic` binary | venv not on PATH | `PATH="$PWD/.venv/bin:$PATH" python -m pytest` |
| CI backend install fails on hatchling | packaging config drift | verify `pyproject.toml` has `[tool.hatch.build.targets.wheel] packages = ["app"]` |

## What's next

- [First-Boot Setup](/docs/first-boot) — the wizard that creates your entity, admin, and fiscal calendar.
- [Configuration](/docs/configuration) — environment variables and AI modes.
- The full operations guide (backups, LAN exposure, demo walkthrough) lives in `docs/SETUP.md` in the repository.
