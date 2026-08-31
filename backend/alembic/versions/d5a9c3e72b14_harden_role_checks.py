"""Harden role checks against NULL role claim

Revision ID: d5a9c3e72b14
Revises: c2e8b1f53a97
Create Date: 2026-08-31

20 legacy RPCs (M2-M6) used the bare pattern:
  IF fn_current_role() NOT IN (...) THEN

When the role claim is missing entirely, fn_current_role()
returns NULL, and NULL NOT IN (...) evaluates to NULL — not
TRUE — so the FORBIDDEN branch was silently skipped
(NULL-bypass). The M7/M8 RPCs already use the hardened form:
  IF fn_current_role() IS NULL OR fn_current_role()
     NOT IN (...) THEN

This migration rewrites the 20 legacy sites to the hardened
form, in place, via CREATE OR REPLACE on the live definition
(catalog state is deterministic: the Alembic chain guarantees
c2e8b1f53a97 ran first).
"""

from alembic import op

revision = "d5a9c3e72b14"
down_revision = "c2e8b1f53a97"
branch_labels = None
depends_on = None

# Every legacy site uses the exact form 'IF fn_current_role() NOT IN'
_OLD = "IF fn_current_role() NOT IN"
_NEW = (
    "IF fn_current_role() IS NULL\n"
    "             OR fn_current_role() NOT IN"
)

# Detection pattern stays exact so hardened sites (which read
# '... IS NULL ... OR fn_current_role() NOT IN') are NOT matched.
_BARE_LIKE = "%IF fn_current_role() NOT IN%"


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.exec_driver_sql(
        "SELECT proname, pg_get_functiondef(oid) AS def "
        "FROM pg_proc "
        "WHERE pronamespace='public'::regnamespace "
        f"AND prosrc LIKE '{_BARE_LIKE}' "
        "ORDER BY proname"
    ).fetchall()
    assert len(rows) == 20, (
        f"expected 20 bare role-check RPCs, found {len(rows)} "
        "— catalog drifted; regenerate this migration"
    )
    for proname, fdef in rows:
        assert _OLD in fdef, f"{proname}: pattern not found"
        conn.exec_driver_sql(fdef.replace(_OLD, _NEW))

    remain = conn.exec_driver_sql(
        "SELECT count(*) FROM pg_proc "
        "WHERE pronamespace='public'::regnamespace "
        f"AND prosrc LIKE '{_BARE_LIKE}'"
    ).scalar_one()
    assert remain == 0, f"{remain} bare role-checks remain"


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.exec_driver_sql(
        "SELECT proname, pg_get_functiondef(oid) AS def "
        "FROM pg_proc "
        "WHERE pronamespace='public'::regnamespace "
        "AND prosrc LIKE '%IS NULL%' "
        "AND prosrc LIKE '%OR fn_current_role() NOT IN%' "
        "ORDER BY proname"
    ).fetchall()
    for proname, fdef in rows:
        if _NEW in fdef:
            conn.exec_driver_sql(fdef.replace(_NEW, _OLD))
