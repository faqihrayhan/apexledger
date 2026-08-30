"""Add trial balance RPC

Revision ID: 711149b12a06
Revises: f563c2d517e9
Create Date: 2026-08-30

Adds ``fn_trial_balance`` — aggregates POSTED journal lines per account
up to an as-of date, producing the classic trial-balance proof that
total debits equal total credits (PRD Modul 1 reporting).

Viewing is allowed for any authenticated member of the entity; the
entity guard itself is enforced inside the RPC (defense in depth).
"""

from alembic import op

revision = "711149b12a06"
down_revision = "f563c2d517e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_trial_balance(
            p_entity_id UUID,
            p_as_of_date DATE DEFAULT NULL
        )
        RETURNS TABLE (
            account_id UUID,
            account_code TEXT,
            account_name TEXT,
            account_type TEXT,
            normal_balance TEXT,
            total_debit NUMERIC,
            total_credit NUMERIC,
            net_debit NUMERIC,
            net_credit NUMERIC
        )
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
            v_as_of DATE := COALESCE(p_as_of_date, CURRENT_DATE);
            v_entity UUID;
        BEGIN
            v_entity := fn_current_entity_id();

            IF v_entity IS NULL OR v_entity <> p_entity_id THEN
                PERFORM fn_raise_error(
                    'FORBIDDEN_ENTITY',
                    'You can only view the trial balance of your own entity.'
                );
            END IF;

            RETURN QUERY
            SELECT
                coa.id,
                coa.account_code::text,
                coa.account_name::text,
                coa.account_type::text,
                coa.normal_balance::text,
                COALESCE(SUM(
                    CASE WHEN je.id IS NOT NULL THEN jl.debit_amount ELSE 0 END
                ), 0) AS total_debit,
                COALESCE(SUM(
                    CASE WHEN je.id IS NOT NULL THEN jl.credit_amount ELSE 0 END
                ), 0) AS total_credit,
                GREATEST(
                    COALESCE(SUM(
                        CASE WHEN je.id IS NOT NULL THEN jl.debit_amount ELSE 0 END
                    ), 0)
                    - COALESCE(SUM(
                        CASE WHEN je.id IS NOT NULL THEN jl.credit_amount ELSE 0 END
                    ), 0), 0
                ) AS net_debit,
                GREATEST(
                    COALESCE(SUM(
                        CASE WHEN je.id IS NOT NULL THEN jl.credit_amount ELSE 0 END
                    ), 0)
                    - COALESCE(SUM(
                        CASE WHEN je.id IS NOT NULL THEN jl.debit_amount ELSE 0 END
                    ), 0), 0
                ) AS net_credit
            FROM chart_of_accounts coa
            LEFT JOIN journal_lines jl
                ON jl.account_id = coa.id
            LEFT JOIN journal_entries je
                ON je.id = jl.journal_entry_id
                AND je.status = 'POSTED'
                AND je.journal_date <= v_as_of
            WHERE coa.entity_id = p_entity_id
                AND coa.is_postable = true
            GROUP BY coa.id
            ORDER BY coa.account_code;
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS fn_trial_balance(UUID, DATE);")
