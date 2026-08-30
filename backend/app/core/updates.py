"""
Opt-in update checker.

Checks for new ApexLedger releases without forcing or auto-installing
anything.  The user is notified in the UI and can choose to update
(or not) at their own pace.

Design principles:
- **Non-intrusive:** Never auto-downloads or auto-installs.
- **Opt-out friendly:** Disabled entirely via APEX_UPDATE_CHECK_ENABLED=false.
- **Privacy-first:** Only sends the current version string; no telemetry.
- **Offline-safe:** Silently skips if the server is unreachable.
"""

from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)


class UpdateInfo(BaseModel):
    """Information about an available update."""

    current_version: str
    latest_version: str
    is_update_available: bool
    release_url: str | None = None
    release_notes: str | None = None


async def check_for_updates() -> UpdateInfo | None:
    """Check the release API for a newer version.

    Returns ``UpdateInfo`` if a newer version exists, ``None`` if
    the check is disabled, the server is unreachable, or we are
    already on the latest version.

    This function is designed to be called from:
    1. A cron job (every ``update_check_interval_hours``).
    2. An explicit ``GET /api/v1/system/updates`` endpoint.
    3. The setup wizard on first boot.

    It never auto-downloads or applies updates — it only reports.
    """
    if not settings.update_check_enabled:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                settings.update_check_url,
                params={"current": settings.app_version},
            )
            resp.raise_for_status()
            data = resp.json()

            latest = data.get("version", settings.app_version)
            is_newer = _is_version_newer(settings.app_version, latest)

            if not is_newer:
                return None

            return UpdateInfo(
                current_version=settings.app_version,
                latest_version=latest,
                is_update_available=True,
                release_url=data.get("url"),
                release_notes=data.get("notes"),
            )

    except (httpx.HTTPError, KeyError, ValueError):
        # Network error, bad response, or malformed JSON — silently skip.
        logger.debug("Update check skipped (server unreachable or bad response).")
        return None


def _is_version_newer(current: str, candidate: str) -> bool:
    """Compare two semver-like version strings (e.g. '0.1.0' vs '0.2.0')."""
    try:
        current_parts = tuple(int(x) for x in current.split("."))
        candidate_parts = tuple(int(x) for x in candidate.split("."))
        return candidate_parts > current_parts
    except (ValueError, AttributeError):
        return False
