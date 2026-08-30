"""Add RLS and RPC functions

Revision ID: 5ee169f912ea
Revises: 2bdbc01edd86
Create Date: 2026-08-30

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5ee169f912ea'
down_revision: str | None = '2bdbc01edd86'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Error Helper Function
    op.execute("""
    CREATE OR REPLACE FUNCTION fn_raise_error(p_code TEXT, p_message TEXT, p_detail JSONB DEFAULT '{}'::jsonb)
    RETURNS VOID LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION '%', p_message
        USING ERRCODE = 'P0001',
              DETAIL = jsonb_build_object('error_code', p_code, 'context', p_detail)::text;
    END;
    $$;
    """)

    # 2. Local Session Helpers (Membaca JWT Claims via FastAPI)
    op.execute("""
    CREATE OR REPLACE FUNCTION fn_current_role() RETURNS role_enum
    LANGUAGE sql STABLE SECURITY DEFINER AS $$
      SELECT NULLIF(current_setting('jwt.claims.role', true), '')::role_enum;
    $$;
    """)

    op.execute("""
    CREATE OR REPLACE FUNCTION fn_current_entity_id() RETURNS UUID
    LANGUAGE sql STABLE SECURITY DEFINER AS $$
      SELECT NULLIF(current_setting('jwt.claims.entity_id', true), '')::uuid;
    $$;
    """)

    op.execute("""
    CREATE OR REPLACE FUNCTION fn_current_user_id() RETURNS UUID
    LANGUAGE sql STABLE SECURITY DEFINER AS $$
      SELECT NULLIF(current_setting('jwt.claims.user_id', true), '')::uuid;
    $$;
    """)

    # 3. RLS Policies
    op.execute("ALTER TABLE entities ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE journal_entries ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE journal_lines ENABLE ROW LEVEL SECURITY;")

    # Entities Policy
    op.execute("""
    CREATE POLICY entities_isolation_policy ON entities
      FOR ALL USING (
        id = fn_current_entity_id() OR fn_current_role() IN ('SUPER_ADMIN', 'IT_ADMIN')
      );
    """)

    # Journal Entries Policy
    op.execute("""
    CREATE POLICY je_select_scoped ON journal_entries 
      FOR SELECT USING (
        entity_id = fn_current_entity_id() OR fn_current_role() IN ('SUPER_ADMIN', 'IT_ADMIN')
      );
    """)

    op.execute("""
    CREATE POLICY je_insert_finance_only ON journal_entries 
      FOR INSERT WITH CHECK (
        entity_id = fn_current_entity_id()
        AND fn_current_role() IN ('FINANCE_OPERATOR', 'DEPT_HEAD_FA', 'SUPER_ADMIN')
      );
    """)

    # Immutable Ledger: Proteksi UPDATE dan DELETE
    op.execute("REVOKE UPDATE, DELETE ON journal_entries, journal_lines FROM PUBLIC;")
    op.execute("REVOKE UPDATE, DELETE ON system_logs FROM PUBLIC;")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS je_insert_finance_only ON journal_entries;")
    op.execute("DROP POLICY IF EXISTS je_select_scoped ON journal_entries;")
    op.execute("DROP POLICY IF EXISTS entities_isolation_policy ON entities;")

    op.execute("ALTER TABLE journal_lines DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE journal_entries DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE user_profiles DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE entities DISABLE ROW LEVEL SECURITY;")

    op.execute("DROP FUNCTION IF EXISTS fn_current_user_id();")
    op.execute("DROP FUNCTION IF EXISTS fn_current_entity_id();")
    op.execute("DROP FUNCTION IF EXISTS fn_current_role();")
    op.execute("DROP FUNCTION IF EXISTS fn_raise_error(TEXT, TEXT, JSONB);")
