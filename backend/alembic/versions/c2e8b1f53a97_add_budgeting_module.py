"""Add Modul 8: Budgeting & Analytics

Revision ID: c2e8b1f53a97
Revises: b9d4f2a8c61e
Create Date: 2026-08-31

Tables: budgets, budget_lines, budget_revisions,
employee_productivity_metrics.
RPCs: fn_create_annual_budget, fn_approve_budget,
fn_lock_budget, fn_revise_budget (audit snapshot),
fn_get_budget_vs_actual, fn_get_monthly_trend,
fn_calculate_employee_productivity_batch (idempotent).

All role checks use the NULL-hardened pattern
(fn_current_role() IS NULL OR NOT IN ...).
"""

from alembic import op

revision = "c2e8b1f53a97"
down_revision = "b9d4f2a8c61e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enums
    # ------------------------------------------------------------------
    op.execute(
        "CREATE TYPE budget_status_enum AS ENUM "
        "('DRAFT','APPROVED','LOCKED')"
    )

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE budgets (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          fiscal_year_id UUID NOT NULL
            REFERENCES fiscal_years(id),
          budget_name VARCHAR(150) NOT NULL,
          status budget_status_enum NOT NULL DEFAULT 'DRAFT',
          created_by UUID NOT NULL
            REFERENCES user_profiles(id),
          approved_by UUID REFERENCES user_profiles(id),
          approved_at TIMESTAMPTZ,
          locked_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entity_id, fiscal_year_id, budget_name)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE budget_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          budget_id UUID NOT NULL
            REFERENCES budgets(id) ON DELETE CASCADE,
          account_id UUID NOT NULL
            REFERENCES chart_of_accounts(id),
          department_code VARCHAR(30),
          period_month SMALLINT NOT NULL
            CHECK (period_month BETWEEN 1 AND 12),
          budgeted_amount NUMERIC(18,2) NOT NULL,
          UNIQUE (budget_id, account_id,
                  department_code, period_month)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE budget_revisions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          budget_id UUID NOT NULL REFERENCES budgets(id),
          revision_number INT NOT NULL,
          revised_by UUID NOT NULL
            REFERENCES user_profiles(id),
          revised_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          reason TEXT NOT NULL,
          before_snapshot JSONB NOT NULL,
          UNIQUE (budget_id, revision_number)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE employee_productivity_metrics (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          employee_id UUID NOT NULL
            REFERENCES employees(id),
          period_year SMALLINT NOT NULL,
          period_month SMALLINT NOT NULL
            CHECK (period_month BETWEEN 1 AND 12),
          metric_code VARCHAR(40) NOT NULL,
          metric_value NUMERIC(18,4) NOT NULL,
          calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (employee_id, period_year,
                  period_month, metric_code)
        )
        """
    )

    # ------------------------------------------------------------------
    # RLS
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE budgets ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY budget_select_scoped ON budgets
        FOR SELECT USING (
          entity_id = fn_current_entity_id()
          OR fn_current_role() IN ('SUPER_ADMIN','IT_ADMIN')
        )
        """
    )
    op.execute("REVOKE ALL ON budgets FROM PUBLIC")

    op.execute(
        "ALTER TABLE budget_lines ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY bl_select_scoped ON budget_lines
        FOR SELECT USING (
          EXISTS (
            SELECT 1 FROM budgets b
            WHERE b.id = budget_lines.budget_id
              AND (b.entity_id = fn_current_entity_id()
                   OR fn_current_role()
                      IN ('SUPER_ADMIN','IT_ADMIN'))
          )
        )
        """
    )
    op.execute("REVOKE ALL ON budget_lines FROM PUBLIC")

    op.execute(
        "ALTER TABLE budget_revisions ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY br_select_scoped ON budget_revisions
        FOR SELECT USING (
          EXISTS (
            SELECT 1 FROM budgets b
            WHERE b.id = budget_revisions.budget_id
              AND (b.entity_id = fn_current_entity_id()
                   OR fn_current_role()
                      IN ('SUPER_ADMIN','IT_ADMIN'))
          )
        )
        """
    )
    op.execute("REVOKE ALL ON budget_revisions FROM PUBLIC")


    # ------------------------------------------------------------------
    # RPC 1: fn_create_annual_budget
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_create_annual_budget(
          p_entity_id UUID, p_fiscal_year_id UUID,
          p_budget_name VARCHAR, p_lines JSONB
        ) RETURNS JSONB LANGUAGE plpgsql
        SECURITY DEFINER AS $$
        DECLARE
          v_budget_id UUID;
          v_line JSONB;
        BEGIN
          IF fn_current_role() IS NULL OR fn_current_role()
             NOT IN ('DEPT_HEAD_FA','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN',
              'Only Head of F&A or Super Admin can '
              'create budgets.');
          END IF;
          IF jsonb_array_length(p_lines) = 0 THEN
            PERFORM fn_raise_error('BUDGET_EMPTY',
              'Budget must have at least one line.');
          END IF;

          INSERT INTO budgets (
            entity_id, fiscal_year_id, budget_name,
            created_by
          ) VALUES (
            p_entity_id, p_fiscal_year_id, p_budget_name,
            fn_current_user_id()
          ) RETURNING id INTO v_budget_id;

          FOR v_line IN
            SELECT * FROM jsonb_array_elements(p_lines)
          LOOP
            IF NOT EXISTS (
              SELECT 1 FROM chart_of_accounts
              WHERE id = (v_line->>'account_id')::uuid
                AND entity_id = p_entity_id
            ) THEN
              PERFORM fn_raise_error('ACCOUNT_NOT_FOUND',
                format('Account %s not found for this '
                       'entity.', v_line->>'account_id'));
            END IF;
            INSERT INTO budget_lines (
              budget_id, account_id, department_code,
              period_month, budgeted_amount
            ) VALUES (
              v_budget_id, (v_line->>'account_id')::uuid,
              v_line->>'department_code',
              (v_line->>'period_month')::smallint,
              (v_line->>'budgeted_amount')::numeric
            );
          END LOOP;

          RETURN jsonb_build_object('budget_id',
                                    v_budget_id);
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 2: fn_approve_budget
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_approve_budget(
          p_budget_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql
        SECURITY DEFINER AS $$
        DECLARE
          v_budget budgets%ROWTYPE;
        BEGIN
          IF fn_current_role() IS NULL OR fn_current_role()
             NOT IN ('DEPT_HEAD_FA','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN',
              'Only Head of F&A or Super Admin can '
              'approve budgets.');
          END IF;
          SELECT * INTO v_budget FROM budgets
            WHERE id = p_budget_id FOR UPDATE;
          IF v_budget.status <> 'DRAFT' THEN
            PERFORM fn_raise_error('BUDGET_INVALID_STATUS',
              format('Budget status is %s, only DRAFT '
                     'can be approved.', v_budget.status));
          END IF;
          UPDATE budgets SET
            status = 'APPROVED',
            approved_by = fn_current_user_id(),
            approved_at = now()
          WHERE id = p_budget_id;
          RETURN jsonb_build_object('budget_id',
            p_budget_id, 'status', 'APPROVED');
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 3: fn_lock_budget
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_lock_budget(
          p_budget_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql
        SECURITY DEFINER AS $$
        DECLARE
          v_budget budgets%ROWTYPE;
        BEGIN
          IF fn_current_role() IS NULL OR fn_current_role()
             <> 'SUPER_ADMIN' THEN
            PERFORM fn_raise_error('FORBIDDEN',
              'Only Super Admin can lock budgets.');
          END IF;
          SELECT * INTO v_budget FROM budgets
            WHERE id = p_budget_id FOR UPDATE;
          IF v_budget.status <> 'APPROVED' THEN
            PERFORM fn_raise_error('BUDGET_INVALID_STATUS',
              'Only APPROVED budgets can be locked.');
          END IF;
          UPDATE budgets SET
            status = 'LOCKED', locked_at = now()
          WHERE id = p_budget_id;
          RETURN jsonb_build_object('budget_id',
            p_budget_id, 'status', 'LOCKED');
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 4: fn_revise_budget (audit snapshot)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_revise_budget(
          p_budget_id UUID, p_new_lines JSONB,
          p_reason TEXT
        ) RETURNS JSONB LANGUAGE plpgsql
        SECURITY DEFINER AS $$
        DECLARE
          v_budget budgets%ROWTYPE;
          v_snapshot JSONB;
          v_rev_no INT;
          v_line JSONB;
        BEGIN
          SELECT * INTO v_budget FROM budgets
            WHERE id = p_budget_id FOR UPDATE;
          IF v_budget.status = 'DRAFT' THEN
            PERFORM fn_raise_error('BUDGET_INVALID_STATUS',
              'DRAFT budgets are edited directly, not '
              'via formal revision.');
          END IF;
          IF v_budget.status = 'LOCKED'
             AND (fn_current_role() IS NULL
                  OR fn_current_role() <> 'SUPER_ADMIN')
          THEN
            PERFORM fn_raise_error('FORBIDDEN',
              'Revising a LOCKED budget requires '
              'Super Admin.');
          END IF;
          IF p_reason IS NULL
             OR length(trim(p_reason)) = 0 THEN
            PERFORM fn_raise_error('REASON_REQUIRED',
              'Revision reason is required for the '
              'audit trail.');
          END IF;
          IF jsonb_array_length(p_new_lines) = 0 THEN
            PERFORM fn_raise_error('BUDGET_EMPTY',
              'Budget must have at least one line.');
          END IF;

          SELECT jsonb_agg(row_to_json(bl))
            INTO v_snapshot
          FROM budget_lines bl
          WHERE bl.budget_id = p_budget_id;
          SELECT COALESCE(MAX(revision_number), 0) + 1
            INTO v_rev_no
          FROM budget_revisions
          WHERE budget_id = p_budget_id;

          INSERT INTO budget_revisions (
            budget_id, revision_number, revised_by,
            reason, before_snapshot
          ) VALUES (
            p_budget_id, v_rev_no, fn_current_user_id(),
            p_reason, v_snapshot
          );

          DELETE FROM budget_lines
            WHERE budget_id = p_budget_id;
          FOR v_line IN
            SELECT * FROM jsonb_array_elements(p_new_lines)
          LOOP
            IF NOT EXISTS (
              SELECT 1 FROM chart_of_accounts
              WHERE id = (v_line->>'account_id')::uuid
                AND entity_id = v_budget.entity_id
            ) THEN
              PERFORM fn_raise_error('ACCOUNT_NOT_FOUND',
                format('Account %s not found for this '
                       'entity.', v_line->>'account_id'));
            END IF;
            INSERT INTO budget_lines (
              budget_id, account_id, department_code,
              period_month, budgeted_amount
            ) VALUES (
              p_budget_id, (v_line->>'account_id')::uuid,
              v_line->>'department_code',
              (v_line->>'period_month')::smallint,
              (v_line->>'budgeted_amount')::numeric
            );
          END LOOP;

          RETURN jsonb_build_object('budget_id',
            p_budget_id, 'revision_number', v_rev_no);
        END;
        $$;
        """
    )


    # ------------------------------------------------------------------
    # RPC 5: fn_get_budget_vs_actual (STABLE read)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_get_budget_vs_actual(
          p_budget_id UUID, p_as_of_month SMALLINT
        ) RETURNS TABLE (
          account_code VARCHAR, account_name VARCHAR,
          department_code VARCHAR,
          budgeted_amount NUMERIC,
          actual_amount NUMERIC,
          variance_amount NUMERIC,
          variance_pct NUMERIC
        ) LANGUAGE plpgsql STABLE AS $$
        DECLARE
          v_budget budgets%ROWTYPE;
        BEGIN
          SELECT * INTO v_budget FROM budgets
            WHERE id = p_budget_id;
          RETURN QUERY
          SELECT
            coa.account_code, coa.account_name,
            bl.department_code,
            SUM(bl.budgeted_amount) AS budgeted_amount,
            COALESCE(act.actual_amount, 0)
              AS actual_amount,
            COALESCE(act.actual_amount, 0)
              - SUM(bl.budgeted_amount)
              AS variance_amount,
            CASE WHEN SUM(bl.budgeted_amount) = 0
              THEN NULL
              ELSE ROUND(
                (COALESCE(act.actual_amount, 0)
                 - SUM(bl.budgeted_amount))
                / SUM(bl.budgeted_amount) * 100, 2)
            END AS variance_pct
          FROM budget_lines bl
          JOIN chart_of_accounts coa
            ON coa.id = bl.account_id
          LEFT JOIN LATERAL (
            SELECT
              CASE WHEN coa.normal_balance = 'DEBIT'
                THEN SUM(jl.debit_amount)
                     - SUM(jl.credit_amount)
                ELSE SUM(jl.credit_amount)
                     - SUM(jl.debit_amount)
              END AS actual_amount
            FROM journal_lines jl
            JOIN journal_entries je
              ON je.id = jl.journal_entry_id
            JOIN fiscal_periods fp
              ON fp.id = je.fiscal_period_id
            WHERE jl.account_id = bl.account_id
              AND je.status = 'POSTED'
              AND fp.fiscal_year_id
                  = v_budget.fiscal_year_id
              AND fp.period_number <= p_as_of_month
          ) act ON TRUE
          WHERE bl.budget_id = p_budget_id
            AND bl.period_month <= p_as_of_month
          GROUP BY coa.account_code, coa.account_name,
                   bl.department_code, act.actual_amount
          ORDER BY coa.account_code;
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 6: fn_get_monthly_trend (STABLE read)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_get_monthly_trend(
          p_entity_id UUID,
          p_account_type account_type_enum,
          p_num_months INT DEFAULT 12
        ) RETURNS TABLE (
          period_year SMALLINT, period_month SMALLINT,
          total_amount NUMERIC
        ) LANGUAGE plpgsql STABLE AS $$
        BEGIN
          RETURN QUERY
          SELECT
            EXTRACT(YEAR FROM fp.start_date)::smallint
              AS period_year,
            fp.period_number::smallint AS period_month,
            SUM(
              CASE WHEN coa.normal_balance = 'DEBIT'
                THEN jl.debit_amount - jl.credit_amount
                ELSE jl.credit_amount - jl.debit_amount
              END
            ) AS total_amount
          FROM journal_lines jl
          JOIN journal_entries je
            ON je.id = jl.journal_entry_id
          JOIN chart_of_accounts coa
            ON coa.id = jl.account_id
          JOIN fiscal_periods fp
            ON fp.id = je.fiscal_period_id
          WHERE coa.entity_id = p_entity_id
            AND coa.account_type = p_account_type
            AND je.status = 'POSTED'
            AND je.journal_date >= (
              CURRENT_DATE
              - (p_num_months || ' months')::interval
            )
          GROUP BY EXTRACT(YEAR FROM fp.start_date),
                   fp.period_number
          ORDER BY 1, 2;
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 7: fn_calculate_employee_productivity_batch
    # (idempotent: ON CONFLICT DO UPDATE)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION
        fn_calculate_employee_productivity_batch(
          p_entity_id UUID, p_period_year SMALLINT,
          p_period_month SMALLINT
        ) RETURNS JSONB LANGUAGE plpgsql
        SECURITY DEFINER AS $$
        DECLARE
          v_sales_emp RECORD;
          v_wh_emp RECORD;
          v_count INT := 0;
        BEGIN
          FOR v_sales_emp IN
            SELECT e.id AS employee_id,
                   SUM(ai.total_amount) AS total_sales
            FROM employees e
            JOIN sales_orders so
              ON so.created_by = e.user_profile_id
             AND so.entity_id = p_entity_id
            JOIN delivery_orders do_
              ON do_.sales_order_id = so.id
            JOIN ar_invoices ai
              ON ai.delivery_order_id = do_.id
            WHERE ai.status <> 'VOID'
              AND EXTRACT(YEAR FROM ai.invoice_date)
                  = p_period_year
              AND EXTRACT(MONTH FROM ai.invoice_date)
                  = p_period_month
            GROUP BY e.id
          LOOP
            INSERT INTO employee_productivity_metrics (
              employee_id, period_year, period_month,
              metric_code, metric_value
            ) VALUES (
              v_sales_emp.employee_id, p_period_year,
              p_period_month,
              'SALES_REVENUE_PER_EMPLOYEE',
              v_sales_emp.total_sales
            ) ON CONFLICT (
              employee_id, period_year, period_month,
              metric_code
            ) DO UPDATE SET
              metric_value = EXCLUDED.metric_value,
              calculated_at = now();
            v_count := v_count + 1;
          END LOOP;

          FOR v_wh_emp IN
            SELECT e.id AS employee_id,
              SUM(wo.qty_produced)
              / NULLIF(SUM(wo.driver_qty_used), 0)
                AS output_per_hour
            FROM employees e
            JOIN work_orders wo
              ON wo.created_by = e.user_profile_id
             AND wo.entity_id = p_entity_id
            WHERE wo.status = 'COMPLETED'
              AND EXTRACT(YEAR FROM wo.completed_at)
                  = p_period_year
              AND EXTRACT(MONTH FROM wo.completed_at)
                  = p_period_month
            GROUP BY e.id
            HAVING SUM(wo.driver_qty_used) > 0
          LOOP
            INSERT INTO employee_productivity_metrics (
              employee_id, period_year, period_month,
              metric_code, metric_value
            ) VALUES (
              v_wh_emp.employee_id, p_period_year,
              p_period_month,
              'PRODUCTION_OUTPUT_PER_LABOR_HOUR',
              v_wh_emp.output_per_hour
            ) ON CONFLICT (
              employee_id, period_year, period_month,
              metric_code
            ) DO UPDATE SET
              metric_value = EXCLUDED.metric_value,
              calculated_at = now();
            v_count := v_count + 1;
          END LOOP;

          RETURN jsonb_build_object(
            'metrics_calculated', v_count);
        END;
        $$;
        """
    )




def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS employee_productivity_metrics"
    )
    op.execute("DROP TABLE IF EXISTS budget_revisions")
    op.execute("DROP TABLE IF EXISTS budget_lines")
    op.execute("DROP TABLE IF EXISTS budgets")
    op.execute("DROP TYPE IF EXISTS budget_status_enum")
