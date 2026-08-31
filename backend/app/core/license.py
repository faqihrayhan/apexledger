"""
License validation (Phase 5 — Gate 5.5, Enterprise Edition).

Offline-tolerant design (PRD: factories/pipelines must keep working
even when the license server is unreachable):
- With no license key configured -> Community Edition, full core
  features, zero phone-home.
- With a key configured -> validate against the license server with
  a cached grace window. If the server is unreachable, the last
  successful validation is trusted for up to GRACE_DAYS.
- The core accounting engine NEVER gates on license status — only
  Enterprise add-ons (turnkey AI, portal sync) do.

Ping is opt-in and scheduled via cron (app/cron/tasks.py), never
blocking requests.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# The last successful validation is cached under ~/.apexledger/license.json
# (survives restarts). See _cache_file() below.

GRACE_DAYS = 14


@dataclass
class LicenseInfo:
    """License state snapshot for the UI/API."""

    edition: str  # "community" | "enterprise"
    valid: bool
    message: str
    expires_at: str | None = None
    grace: bool = False


def _cache_file() -> Path:
    from pathlib import Path

    return Path.home() / ".apexledger" / "license.json"


async def validate_license_online() -> LicenseInfo:
    """Ping the license server and cache the result."""
    if not settings.license_key:
        return LicenseInfo(
            edition="community",
            valid=True,
            message="Community Edition — no license key configured.",
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                settings.license_server_url,
                json={"license_key": settings.license_key},
            )
            resp.raise_for_status()
            data = resp.json()

        info = LicenseInfo(
            edition="enterprise",
            valid=bool(data.get("valid", False)),
            message=data.get("message", "Validated"),
            expires_at=data.get("expires_at"),
        )
        _write_cache(info)
        return info

    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("License server unreachable: %s", exc)
        return _cached_or_grace()


def _write_cache(info: LicenseInfo) -> None:
    """Persist the last successful validation."""

    path = _cache_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "edition": info.edition,
        "valid": info.valid,
        "message": info.message,
        "expires_at": info.expires_at,
        "validated_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(payload))


def _cached_or_grace() -> LicenseInfo:
    """Fall back to the cached validation inside the grace window."""

    path = _cache_file()
    if not path.exists():
        return LicenseInfo(
            edition="community",
            valid=True,
            message="License server unreachable; running Community features.",
            grace=True,
        )

    try:
        payload = json.loads(path.read_text())
    except ValueError:
        return LicenseInfo(
            edition="community", valid=True, message="Cache unreadable.", grace=True
        )

    validated_at = datetime.fromisoformat(payload["validated_at"])
    age = datetime.now(UTC) - validated_at
    if age <= timedelta(days=GRACE_DAYS):
        return LicenseInfo(
            edition=payload.get("edition", "community"),
            valid=payload.get("valid", False),
            message=payload.get("message", "") + " (offline grace)",
            expires_at=payload.get("expires_at"),
            grace=True,
        )

    return LicenseInfo(
        edition="community",
        valid=False,
        message=(
            f"License could not be validated for {age.days} days "
            f"(grace is {GRACE_DAYS} days). Enterprise features paused."
        ),
    )


def license_status() -> LicenseInfo:
    """Synchronous snapshot (cached, no network) for the CLI."""
    if not settings.license_key:
        return LicenseInfo(
            edition="community",
            valid=True,
            message="Community Edition — no license key configured.",
        )
    return _cached_or_grace()
