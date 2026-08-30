"""
Maps PL/pgSQL RPC exceptions (P0001 + JSON DETAIL) into clean HTTP errors.

Every module RPC raises via ``fn_raise_error(p_code, p_message)``, which
encodes ``{"error_code": ..., "context": ...}`` in the Postgres DETAIL.
Under asyncpg + SQLAlchemy 2, the underlying asyncpg PostgresError carries
both ``.detail`` and ``.message``.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import DBAPIError


def _extract_pg_fields(exc: DBAPIError) -> tuple[str | None, str | None, str | None]:
    """Pull (sqlstate, message, detail) out of arbitrary SQLAlchemy DBAPIErrors.

    asyncpg packs everything into ``orig.args[0]`` as a single string shaped
    ``"<class RaiseError>: message\\nDETAIL:  {json}"`` — so we parse that
    as a fallback when real attributes are missing.
    """
    orig: Any = getattr(exc, "orig", None)
    if orig is None:
        return None, None, None

    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)

    message: str | None = getattr(orig, "message", None)
    detail: str | None = getattr(orig, "detail", None)

    raw = ""
    args = getattr(orig, "args", None)
    if args:
        raw = str(args[0])

    if not detail and "DETAIL:" in raw:
        detail = raw.split("DETAIL:", 1)[1].strip()
    if not message and raw:
        # Strip the "<class '...'>: " prefix and any trailing DETAIL section.
        message = raw.split(":", 1)[-1].split("\nDETAIL:")[0].strip() if ":" in raw else raw

    return sqlstate, message, detail


def raise_from_rpc(exc: DBAPIError) -> HTTPException:
    """Convert a DBAPIError raised by an RPC into an HTTPException.

    Unknown/non-RPC database errors are re-raised so they bubble up as 500.
    """
    sqlstate, message, detail_raw = _extract_pg_fields(exc)

    if sqlstate == "P0001":
        error_code = "RPC_ERROR"
        if detail_raw:
            try:
                detail_obj = json.loads(detail_raw)
                error_code = detail_obj.get("error_code", error_code)
            except (ValueError, TypeError):
                # Detail was not JSON; use raw detail string if short.
                error_code = detail_raw[:64]

        # Determine HTTP status code based on semantic error class.
        http_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        if error_code in ("UNAUTHENTICATED",):
            http_code = status.HTTP_401_UNAUTHORIZED
        elif "FORBIDDEN" in str(error_code):
            http_code = status.HTTP_403_FORBIDDEN

        return HTTPException(
            status_code=http_code,
            detail={
                "error_code": error_code,
                "message": message or "RPC business rule rejected the request.",
            },
        )

    raise exc
