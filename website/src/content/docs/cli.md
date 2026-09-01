# CLI Reference

Six operational commands run the whole server lifecycle from `backend/` — no Docker Compose file, no Makefile, no shell scripting. Every command is idempotent where it matters.

All commands run from `backend/` with the virtual environment active:

```bash
cd backend && source .venv/bin/activate
```

## The six commands

| Command | Purpose |
|---|---|
| `python cli.py init` | start container + wait ready + run migrations |
| `python cli.py serve` | run the API server (wraps uvicorn) |
| `python cli.py backup` | `pg_dump` → `backups/apexledger-<ts>.sql.gz` |
| `python cli.py update` | check for updates (opt-in, no forced upgrade) |
| `python cli.py status` | container + migration health overview |
| `python cli.py license` | show license status (Community: no key needed) |

## init — bootstrap the machine

```bash
python cli.py init
```

Starts the Postgres container, **waits until it is actually ready** (not just started), then applies every Alembic migration — tables, RLS policies, and all 49 RPCs. Zero manual SQL.

Safe to re-run: an initialized machine just gets a migration no-op.

## serve — run the API

```bash
python cli.py serve
```

Wraps `uvicorn main:app` — the same module path you would type by hand. For LAN access from the [desktop app](/docs/installation), expose the interface: `uvicorn main:app --host 0.0.0.0`.

## backup — one-file disaster recovery

```bash
python cli.py backup
```

Runs `pg_dump` and writes a timestamped, gzipped SQL dump to `backups/apexledger-<ts>.sql.gz`. Restore with `psql` (or `pg_restore` tooling of your choice) into a fresh database, then `alembic upgrade head` if the target is behind. Run it before every upgrade, and on a schedule you trust.

## update — opt-in only

```bash
python cli.py update
```

Checks for available updates. It **never upgrades on its own** — you see what's pending and decide. No phone-home unless you ask.

## status — the health overview

```bash
python cli.py status
```

One screen: is the container running, is the schema at the latest migration. Run this first whenever "something is wrong".

## license

```bash
python cli.py license
```

Prints the license state. Community edition needs no key — this command exists for the [Enterprise](/#editions) features.

## Tests & lint

```bash
# from backend/ — the venv must be on PATH so conftest can call alembic
PATH="$PWD/.venv/bin:$PATH" python -m pytest -q
ruff check app tests cli.py

# from frontend/
npx eslint src
npx tsc -b --noEmit
npm run build
```

Two things worth knowing:

- **The test suite is isolated by design.** `tests/conftest.py` drops/creates a dedicated `apexledger_test` database per session and truncates between tests — it never touches your dev data.
- **Assertions verify business math**, not just status codes — a payroll test checks the net pay, not the HTTP 200.
- **The PATH trick matters**: conftest shells out to `alembic`, which must resolve to the venv's binary — the classic symptom of skipping it is pytest failing to find `alembic`.

## What's next

- [Installation](/docs/installation) — where `init` first runs.
- [Configuration](/docs/configuration) — the env vars these commands read.
