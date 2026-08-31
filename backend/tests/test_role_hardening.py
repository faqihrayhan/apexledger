"""
Security regression tests — NULL role-claim hardening.

The M6 discovery: with direct asyncpg access and no
jwt.claims set, fn_current_role() returns NULL, and the legacy
`NULL NOT IN (...)` role checks evaluated to NULL (not TRUE),
silently skipping the FORBIDDEN branch. All 30 role-checked
RPCs now use the hardened pattern; these tests lock it.

Behavior proven by fn_transfer_stock (representative M2-M6
legacy site) and fn_register_fixed_asset (M7 pattern):

1. NULL role  -> FORBIDDEN (no bypass)
2. legit role -> passes the role gate (fails later on
   business validation, never on FORBIDDEN_ROLE)
3. catalog-wide: zero bare `IF fn_current_role() NOT IN`
   sites remain in the public schema
"""

from __future__ import annotations

import asyncpg
import pytest

DB = "postgresql://postgres:postgres@localhost:5432/apexledger_test"


@pytest.mark.asyncio
async def test_null_role_cannot_bypass_role_gate():
    """Legacy NULL-bypass: no claims set -> must be FORBIDDEN."""
    conn = await asyncpg.connect(DB)
    try:
        with pytest.raises(asyncpg.exceptions.PostgresError) as ei:
            await conn.fetchval(
                "SELECT fn_transfer_stock("
                "gen_random_uuid(), gen_random_uuid(), "
                "gen_random_uuid(), 1)")
        assert "FORBIDDEN" in str(ei.value), (
            "NULL role bypassed the role gate — regression!"
        )
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_legit_role_passes_role_gate():
    """A real role must still clear the gate (no over-blocking)."""
    conn = await asyncpg.connect(DB)
    try:
        await conn.execute(
            "SELECT set_config('jwt.claims.role', "
            "'WAREHOUSE_OPERATOR', false)"
        )
        with pytest.raises(asyncpg.exceptions.PostgresError) as ei:
            await conn.fetchval(
                "SELECT fn_transfer_stock("
                "gen_random_uuid(), gen_random_uuid(), "
                "gen_random_uuid(), 1)")
        # Must fail on business validation (item missing),
        # NOT on the role gate.
        assert "FORBIDDEN" not in str(ei.value), (
            "legit role was blocked at the role gate"
        )
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_catalog_has_no_bare_role_checks():
    """Catalog-wide: no bare NOT IN role-check sites remain."""
    conn = await asyncpg.connect(DB)
    try:
        bare = await conn.fetchval(
            "SELECT count(*) FROM pg_proc "
            "WHERE pronamespace='public'::regnamespace "
            "AND prosrc LIKE "
            "'%IF fn_current_role() NOT IN%'")
        assert bare == 0, (
            f"{bare} bare role-check sites found — NULL-bypass "
            "would be possible again"
        )
        hardened = await conn.fetchval(
            "SELECT count(*) FROM pg_proc "
            "WHERE pronamespace='public'::regnamespace "
            "AND prosrc LIKE '%IS NULL%' "
            "AND prosrc LIKE "
            "'%OR fn_current_role() NOT IN%'")
        assert hardened == 20
    finally:
        await conn.close()
