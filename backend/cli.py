"""
ApexLedger CLI — installer & lifecycle manager (Phase 5 — Gate 5.3/5.6).

Commands:
    init        Prepare the local database (docker container + migrations).
    serve       Run the backend API server (uvicorn).
    backup      Dump the database to a timestamped .sql.gz file (auto-backup
                before any update, or on demand).
    update      Check for updates (opt-in, never auto-installs).
    status      Instance + database + migration health at a glance.
    license     Show license status (Enterprise).

Design notes:
- Zero manual SQL for the user: ``init`` handles container, database,
  and migrations end to end.
- ``backup`` writes to ``backups/`` next to the repo root and prints
  the absolute path. Uses pg_dump inside the docker container (the
  host may not have pg_dump installed).
- Everything is safe to re-run (idempotent).
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Resolve the backend directory regardless of how the CLI is invoked.
# cli.py lives in backend/, so its parent IS the backend package root
# (where alembic.ini, app/, and .venv live).
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

CONTAINER_NAME = "apexledger-db"
DB_NAME = "apexledger"
DB_USER = "postgres"
DB_PORT = "5432"


def _is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def _backups_dir() -> Path:
    """Stable backups directory.

    Frozen binary: ~/.apexledger/backups (the extraction temp dir would
    vanish). Source checkout: <repo>/backups next to the backend dir.
    """
    if _is_frozen():
        return Path.home() / ".apexledger" / "backups"
    return BACKEND_DIR.parent / "backups"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a subprocess, streaming output to the terminal."""
    return subprocess.run(cmd, check=True, cwd=str(BACKEND_DIR), **kwargs)


def _docker_available() -> bool:
    try:
        _run(["docker", "info"], capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _container_running() -> bool:
    try:
        result = _run(
            ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() == "true"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _ensure_container() -> str:
    """Ensure the Postgres container exists and is running; return status."""
    if not _docker_available():
        return "docker-unavailable"

    try:
        _run(["docker", "inspect", CONTAINER_NAME], capture_output=True)
        if not _container_running():
            _run(["docker", "start", CONTAINER_NAME])
            return "started"
        return "running"
    except subprocess.CalledProcessError:
        # Container doesn't exist yet — create it.
        _run(
            [
                "docker", "run", "-d",
                "--name", CONTAINER_NAME,
                "-e", f"POSTGRES_PASSWORD={os.environ.get('POSTGRES_PASSWORD', 'postgres')}",
                "-e", f"POSTGRES_DB={DB_NAME}",
                "-p", f"{DB_PORT}:5432",
                "postgres:15",
            ]
        )
        return "created"


def cmd_init(args: argparse.Namespace) -> int:
    """One-click setup: container + database + migrations."""
    print("ApexLedger init — preparing local database…")

    status = _ensure_container()
    if status == "docker-unavailable":
        print("ERROR: Docker is not running or not installed.")
        return 1
    print(f"  container: {status}")

    # Wait for Postgres to accept connections (up to ~30s).
    import time

    for _attempt in range(30):
        try:
            _run(
                [
                    "docker", "exec", CONTAINER_NAME,
                    "pg_isready", "-U", DB_USER,
                ],
                capture_output=True,
            )
            break
        except subprocess.CalledProcessError:
            time.sleep(1)
    else:
        print("ERROR: Postgres did not become ready in 30s.")
        return 1
    print("  postgres: ready")

    # Apply migrations.
    venv_alembic = BACKEND_DIR / ".venv" / "bin" / "alembic"
    if venv_alembic.exists():
        alembic_cmd = [str(venv_alembic), "upgrade", "head"]
    else:
        alembic_cmd = ["alembic", "upgrade", "head"]
    try:
        _run(alembic_cmd)
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: migrations failed: {exc}")
        return 1
    print("  migrations: head applied")

    print("Done. Start the server with: apexledger serve")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the backend API with uvicorn."""
    venv_uvicorn = BACKEND_DIR / ".venv" / "bin" / "uvicorn"
    port = str(args.port)
    cmd = (
        [str(venv_uvicorn), "main:app", "--host", "0.0.0.0", "--port", port]
        if venv_uvicorn.exists()
        else ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", port]
    )
    print(f"Starting ApexLedger API on port {port} …")
    _run(cmd)
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    """Dump the database to backups/<timestamp>.sql.gz."""
    if not _container_running():
        print("ERROR: database container is not running.")
        return 1

    backups_dir = _backups_dir()
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backups_dir / f"{DB_NAME}-{stamp}.sql.gz"

    print("Dumping database…")
    dump = subprocess.run(
        [
            "docker", "exec", CONTAINER_NAME,
            "pg_dump", "-U", DB_USER, "--no-owner", DB_NAME,
        ],
        check=True,
        capture_output=True,
    )
    with gzip.open(target, "wb") as f:
        f.write(dump.stdout)

    size_kb = target.stat().st_size / 1024
    print(f"  backup: {target} ({size_kb:.1f} KB)")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    """Opt-in update check (never auto-installs)."""
    # Import lazily — needs the venv's app modules.
    from app.core.config import settings
    from app.core.updates import check_for_updates

    print(f"ApexLedger {settings.app_version} — checking for updates…")
    info = asyncio.run(check_for_updates())
    if info is None:
        print("You are on the latest version (or checks are disabled).")
        return 0
    print(f"  update available: {info.latest_version}")
    if info.release_url:
        print(f"  download: {info.release_url}")
    print("This CLI never auto-installs. Review and update manually.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Instance health at a glance."""
    from app.core.config import settings

    print(f"ApexLedger {settings.app_version} (mode={settings.app_mode})")
    print(f"  ai_mode   : {settings.ai_mode}")

    container = "running" if _container_running() else "stopped"
    print(f"  container : {container}")

    try:
        result = _run(
            [str(BACKEND_DIR / ".venv" / "bin" / "alembic"), "current"],
            capture_output=True,
            text=True,
        )
        head = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "unknown"
        print(f"  migration : {head}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("  migration : unknown (alembic not found)")

    return 0


def cmd_license(args: argparse.Namespace) -> int:
    """Show license status (Enterprise)."""
    # License validation is implemented in app/core/license.py — import
    # lazily so Community users without the module never hit this path.
    try:
        from app.core.license import license_status
    except ImportError:
        print("License: Community Edition (no license key configured).")
        return 0

    status = license_status()
    print(f"License: {status}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apexledger",
        description="ApexLedger — on-premise accounting platform CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="prepare container + run migrations")
    p_init.set_defaults(func=cmd_init)

    p_serve = sub.add_parser("serve", help="run the API server")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=cmd_serve)

    p_backup = sub.add_parser("backup", help="dump the database (auto-gzip)")
    p_backup.set_defaults(func=cmd_backup)

    p_update = sub.add_parser("update", help="check for updates (opt-in)")
    p_update.set_defaults(func=cmd_update)

    p_status = sub.add_parser("status", help="instance health overview")
    p_status.set_defaults(func=cmd_status)

    p_license = sub.add_parser("license", help="show license status")
    p_license.set_defaults(func=cmd_license)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
