"""Add GL RPC and CoA RLS

Revision ID: f563c2d517e9
Revises: 49ca92cd8b4e
Create Date: 2026-08-30

Implements Module 1 business logic as PL/pgSQL RPCs (PRD Modul 1),
adapted from Supabase ``auth.uid()`` to the local JWT claims context
(``fn_current_user_id()`` / ``fn_current_role()`` / ``fn_current_entity_id()``).
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f563c2d517e9"
down_revision: str | None = "49ca92cd8b4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# fn_create_journal_entry — atomic header + lines insert with full validation
# ---------------------------------------------------------------------------
CREATE_JE_FN = """
CREATE OR REPLACE FUNCTION fn_create_journal_entry(
  p_entity_id UUID,
  p_journal_date DATE,
  p_description TEXT,
  p_currency_code CHAR(3),
  p_lines JSONB
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  v_period_id      UUID;
  v_period_status  VARCHAR(10);
  v_entry_id       UUID;
  v_line           JSONB;
  v_line_no        SMALLINT := 1;
  v_debit_sum      NUMERIC(18,2) := 0;
  v_credit_sum     NUMERIC(18,2) := 0;
  v_journal_number VARCHAR(30);
  v_seq_name       TEXT;
  v_next_val       BIGINT;
  v_user_id        UUID;
  v_role           role_enum;
BEGIN
  -- Auth guard: the calling session must carry JWT claims (injected by FastAPI).
  v_user_id := fn_current_user_id();
  IF v_user_id IS NULL THEN
    PERFORM fn_raise_error('UNAUTHENTICATED', 'Journal creation requires an authenticated session.');
  END IF;

  v_role := fn_current_role();
  IF v_role IS NULL OR v_role NOT IN ('FINANCE_OPERATOR','DEPT_HEAD_FA','SUPER_ADMIN','IT_ADMIN') THEN
    PERFORM fn_raise_error('FORBIDDEN_ROLE', format('Role %s is not allowed to create journal entries.', v_role));
  END IF;

  IF fn_current_entity_id() IS DISTINCT FROM p_entity_id
     AND v_role NOT IN ('SUPER_ADMIN','IT_ADMIN') THEN
    PERFORM fn_raise_error('FORBIDDEN_ENTITY', 'You can only create entries for your own entity.');
  END IF;

  IF jsonb_array_length(p_lines) < 2 THEN
    PERFORM fn_raise_error('JE_MIN_LINES', 'Journal entry requires at least 2 lines (double-entry).');
  END IF;

  SELECT fp.id, fp.status INTO v_period_id, v_period_status
    FROM fiscal_periods fp
    JOIN fiscal_years fy ON fy.id = fp.fiscal_year_id
    WHERE fy.entity_id = p_entity_id
      AND p_journal_date BETWEEN fp.start_date AND fp.end_date;

  IF v_period_id IS NULL THEN
    PERFORM fn_raise_error('PERIOD_NOT_FOUND', 'No fiscal period covers this transaction date.');
  END IF;
  IF v_period_status <> 'OPEN' THEN
    PERFORM fn_raise_error('PERIOD_CLOSED', 'The fiscal period for this date is closed.');
  END IF;

  -- Validate every line: account must be postable, active, and owned by the entity.
  FOR v_line IN SELECT * FROM jsonb_array_elements(p_lines) LOOP
    IF NOT EXISTS (
      SELECT 1 FROM chart_of_accounts
      WHERE id = (v_line->>'account_id')::uuid
        AND entity_id = p_entity_id AND is_postable = TRUE AND is_active = TRUE
    ) THEN
      PERFORM fn_raise_error('ACCOUNT_NOT_POSTABLE',
        format('Account %s is not a postable/active account for this entity.', v_line->>'account_id'));
    END IF;
    v_debit_sum  := v_debit_sum  + COALESCE((v_line->>'debit_amount')::numeric, 0);
    v_credit_sum := v_credit_sum + COALESCE((v_line->>'credit_amount')::numeric, 0);
  END LOOP;

  IF v_debit_sum <> v_credit_sum THEN
    PERFORM fn_raise_error('JE_UNBALANCED',
      format('Debit total (%s) does not equal credit total (%s).', v_debit_sum, v_credit_sum));
  END IF;

  IF v_debit_sum = 0 THEN
    PERFORM fn_raise_error('JE_ZERO_AMOUNT', 'Journal entry total cannot be zero.');
  END IF;

  -- Per-entity journal numbering sequence (PRD Edge Case #11: sanitized name).
  v_seq_name := 'seq_journal_number_' || replace(p_entity_id::text, '-', '_');
  EXECUTE format('CREATE SEQUENCE IF NOT EXISTS %I START 1', v_seq_name);
  EXECUTE format('SELECT nextval(%L)', v_seq_name) INTO v_next_val;

  v_journal_number := 'JE-' || to_char(p_journal_date, 'YYYYMM') || '-' || lpad(v_next_val::text, 5, '0');

  INSERT INTO journal_entries (
    entity_id, journal_number, journal_date, fiscal_period_id,
    source_module, description, currency_code, exchange_rate, is_reversal, status, created_by
  ) VALUES (
    p_entity_id, v_journal_number, p_journal_date, v_period_id,
    'GL_MANUAL', p_description, p_currency_code, 1.0, false, 'DRAFT', v_user_id
  ) RETURNING id INTO v_entry_id;

  FOR v_line IN SELECT * FROM jsonb_array_elements(p_lines) LOOP
    INSERT INTO journal_lines (
      journal_entry_id, line_number, account_id,
      debit_amount, credit_amount, base_currency_amount,
      department_code, description
    ) VALUES (
      v_entry_id, v_line_no, (v_line->>'account_id')::uuid,
      COALESCE((v_line->>'debit_amount')::numeric, 0),
      COALESCE((v_line->>'credit_amount')::numeric, 0),
      GREATEST(COALESCE((v_line->>'debit_amount')::numeric,0), COALESCE((v_line->>'credit_amount')::numeric,0)),
      v_line->>'department_code', v_line->>'description'
    );
    v_line_no := v_line_no + 1;
  END LOOP;

  INSERT INTO system_logs(actor_id, entity_id, action, table_name, record_id, after_data)
    VALUES (v_user_id, p_entity_id, 'INSERT', 'journal_entries', v_entry_id::text,
      jsonb_build_object('journal_number', v_journal_number, 'line_count', jsonb_array_length(p_lines)));

  RETURN jsonb_build_object('success', true, 'journal_entry_id', v_entry_id, 'journal_number', v_journal_number);
EXCEPTION
  WHEN OTHERS THEN
    RAISE;  -- header + lines roll back atomically if any line fails
END;
$$;
"""

# ---------------------------------------------------------------------------
# fn_post_journal_entry — DRAFT -> POSTED with row lock + balance re-check
# ---------------------------------------------------------------------------
POST_JE_FN = """
CREATE OR REPLACE FUNCTION fn_post_journal_entry(p_journal_entry_id UUID)
RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  v_entry         journal_entries%ROWTYPE;
  v_debit_sum     NUMERIC(18,2);
  v_credit_sum    NUMERIC(18,2);
  v_period_status VARCHAR(10);
  v_user_id       UUID;
  v_role          role_enum;
BEGIN
  v_user_id := fn_current_user_id();
  IF v_user_id IS NULL THEN
    PERFORM fn_raise_error('UNAUTHENTICATED', 'Posting requires an authenticated session.');
  END IF;

  v_role := fn_current_role();
  IF v_role IS NULL OR v_role NOT IN ('FINANCE_OPERATOR','DEPT_HEAD_FA','SUPER_ADMIN','IT_ADMIN') THEN
    PERFORM fn_raise_error('FORBIDDEN_ROLE', format('Role %s is not allowed to post journal entries.', v_role));
  END IF;

  SELECT * INTO v_entry FROM journal_entries WHERE id = p_journal_entry_id FOR UPDATE;
  IF NOT FOUND THEN
    PERFORM fn_raise_error('JE_NOT_FOUND', 'Journal entry not found.');
  END IF;

  IF fn_current_entity_id() IS DISTINCT FROM v_entry.entity_id
     AND v_role NOT IN ('SUPER_ADMIN','IT_ADMIN') THEN
    PERFORM fn_raise_error('FORBIDDEN_ENTITY', 'You can only post entries for your own entity.');
  END IF;

  IF v_entry.status <> 'DRAFT' THEN
    PERFORM fn_raise_error('JE_INVALID_STATUS',
      format('Journal entry status is %s; only DRAFT entries can be posted.', v_entry.status));
  END IF;

  SELECT status INTO v_period_status FROM fiscal_periods WHERE id = v_entry.fiscal_period_id;
  IF v_period_status <> 'OPEN' THEN
    PERFORM fn_raise_error('PERIOD_CLOSED', 'The fiscal period is closed; posting denied.');
  END IF;

  SELECT COALESCE(SUM(debit_amount),0), COALESCE(SUM(credit_amount),0)
    INTO v_debit_sum, v_credit_sum
    FROM journal_lines WHERE journal_entry_id = p_journal_entry_id;

  IF v_debit_sum <> v_credit_sum THEN
    PERFORM fn_raise_error('JE_UNBALANCED',
      format('Debit total (%s) does not equal credit total (%s).', v_debit_sum, v_credit_sum));
  END IF;

  UPDATE journal_entries SET status = 'POSTED', posted_by = v_user_id, posted_at = now()
    WHERE id = p_journal_entry_id;

  INSERT INTO system_logs(actor_id, entity_id, action, table_name, record_id, after_data)
    VALUES (v_user_id, v_entry.entity_id, 'POST', 'journal_entries', p_journal_entry_id::text,
      jsonb_build_object('status','POSTED','debit_sum',v_debit_sum,'credit_sum',v_credit_sum));

  RETURN jsonb_build_object('success', true, 'journal_entry_id', p_journal_entry_id,
    'status', 'POSTED', 'debit_total', v_debit_sum, 'credit_total', v_credit_sum);
EXCEPTION
  WHEN OTHERS THEN RAISE;
END;
$$;
"""

# ---------------------------------------------------------------------------
# fn_reverse_journal_entry — creates + posts the mirror entry, marks original
# ---------------------------------------------------------------------------
REVERSE_JE_FN = """
CREATE OR REPLACE FUNCTION fn_reverse_journal_entry(
  p_journal_entry_id UUID,
  p_reversal_date DATE,
  p_reason TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  v_original     journal_entries%ROWTYPE;
  v_new_entry_id UUID;
  v_period_id     UUID;
  v_line          RECORD;
  v_line_no       SMALLINT := 1;
  v_user_id       UUID;
  v_role          role_enum;
BEGIN
  v_user_id := fn_current_user_id();
  IF v_user_id IS NULL THEN
    PERFORM fn_raise_error('UNAUTHENTICATED', 'Reversal requires an authenticated session.');
  END IF;

  v_role := fn_current_role();
  IF v_role IS NULL OR v_role NOT IN ('FINANCE_OPERATOR','DEPT_HEAD_FA','SUPER_ADMIN','IT_ADMIN') THEN
    PERFORM fn_raise_error('FORBIDDEN_ROLE', format('Role %s is not allowed to reverse entries.', v_role));
  END IF;

  SELECT * INTO v_original FROM journal_entries WHERE id = p_journal_entry_id FOR UPDATE;
  IF NOT FOUND THEN
    PERFORM fn_raise_error('JE_NOT_FOUND', 'Source journal entry not found.');
  END IF;

  IF fn_current_entity_id() IS DISTINCT FROM v_original.entity_id
     AND v_role NOT IN ('SUPER_ADMIN','IT_ADMIN') THEN
    PERFORM fn_raise_error('FORBIDDEN_ENTITY', 'You can only reverse entries for your own entity.');
  END IF;

  IF v_original.reversed_entry_id IS NOT NULL OR v_original.status = 'REVERSED' THEN
    PERFORM fn_raise_error('JE_ALREADY_REVERSED', 'This journal entry has already been reversed.');
  END IF;

  IF v_original.status <> 'POSTED' THEN
    PERFORM fn_raise_error('JE_NOT_POSTED', 'Only POSTED entries can be reversed.');
  END IF;

  SELECT fp.id INTO v_period_id FROM fiscal_periods fp
    JOIN fiscal_years fy ON fy.id = fp.fiscal_year_id
    WHERE fy.entity_id = v_original.entity_id
      AND p_reversal_date BETWEEN fp.start_date AND fp.end_date;
  IF v_period_id IS NULL THEN
    PERFORM fn_raise_error('PERIOD_NOT_FOUND', 'No fiscal period covers the reversal date.');
  END IF;

  INSERT INTO journal_entries (
    entity_id, journal_number, journal_date, fiscal_period_id, source_module,
    source_reference_id, description, currency_code, exchange_rate,
    status, is_reversal, created_by
  ) VALUES (
    v_original.entity_id, v_original.journal_number || '-REV', p_reversal_date, v_period_id,
    v_original.source_module, v_original.id,
    'Reversal: ' || COALESCE(p_reason, v_original.description),
    v_original.currency_code, v_original.exchange_rate,
    'DRAFT', TRUE, v_user_id
  ) RETURNING id INTO v_new_entry_id;

  -- Mirror every line: debit <-> credit swapped.
  FOR v_line IN SELECT * FROM journal_lines WHERE journal_entry_id = p_journal_entry_id LOOP
    INSERT INTO journal_lines (
      journal_entry_id, line_number, account_id, debit_amount, credit_amount,
      base_currency_amount, department_code, project_id, cost_center_code, description
    ) VALUES (
      v_new_entry_id, v_line_no, v_line.account_id,
      v_line.credit_amount, v_line.debit_amount, v_line.base_currency_amount,
      v_line.department_code, v_line.project_id, v_line.cost_center_code,
      'Reversal of line ' || v_line.line_number
    );
    v_line_no := v_line_no + 1;
  END LOOP;

  PERFORM fn_post_journal_entry(v_new_entry_id);

  UPDATE journal_entries SET status = 'REVERSED', reversed_entry_id = v_new_entry_id
    WHERE id = p_journal_entry_id;

  INSERT INTO system_logs(actor_id, entity_id, action, table_name, record_id, after_data)
    VALUES (v_user_id, v_original.entity_id, 'REVERSE', 'journal_entries', p_journal_entry_id::text,
      jsonb_build_object('reversal_entry_id', v_new_entry_id, 'reason', p_reason));

  RETURN jsonb_build_object('success', true,
    'original_entry_id', p_journal_entry_id, 'original_status', 'REVERSED',
    'reversal_entry_id', v_new_entry_id,
    'reversal_number', v_original.journal_number || '-REV');
EXCEPTION
  WHEN OTHERS THEN RAISE;
END;
$$;
"""


def upgrade() -> None:
    # --- RPC functions (one command each) ---
    op.execute(CREATE_JE_FN)
    op.execute(POST_JE_FN)
    op.execute(REVERSE_JE_FN)

    # --- RLS: chart of accounts ---
    op.execute("ALTER TABLE chart_of_accounts ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY coa_select_scoped ON chart_of_accounts FOR SELECT USING ("
        " entity_id = fn_current_entity_id()"
        " OR fn_current_role() IN ('SUPER_ADMIN','IT_ADMIN'));"
    )
    op.execute(
        "CREATE POLICY coa_modify_finance ON chart_of_accounts FOR ALL"
        " USING (entity_id = fn_current_entity_id()"
        "  OR fn_current_role() IN ('SUPER_ADMIN','IT_ADMIN'))"
        " WITH CHECK (entity_id = fn_current_entity_id()"
        "  AND fn_current_role() IN ('FINANCE_OPERATOR','DEPT_HEAD_FA','SUPER_ADMIN','IT_ADMIN'));"
    )

    # --- RLS: fiscal years & periods ---
    op.execute("ALTER TABLE fiscal_years ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY fy_select_scoped ON fiscal_years FOR SELECT USING ("
        " entity_id = fn_current_entity_id()"
        " OR fn_current_role() IN ('SUPER_ADMIN','IT_ADMIN'));"
    )
    op.execute("ALTER TABLE fiscal_periods ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY fp_select_scoped ON fiscal_periods FOR SELECT USING ("
        " EXISTS (SELECT 1 FROM fiscal_years fy"
        "   WHERE fy.id = fiscal_periods.fiscal_year_id"
        "   AND (fy.entity_id = fn_current_entity_id()"
        "        OR fn_current_role() IN ('SUPER_ADMIN','IT_ADMIN'))));"
    )

    # --- RLS: journal lines (RLS was enabled in the previous migration) ---
    op.execute(
        "CREATE POLICY jl_select_scoped ON journal_lines FOR SELECT USING ("
        " EXISTS (SELECT 1 FROM journal_entries je"
        "   WHERE je.id = journal_lines.journal_entry_id"
        "   AND (je.entity_id = fn_current_entity_id()"
        "        OR fn_current_role() IN ('SUPER_ADMIN','IT_ADMIN'))));"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS jl_select_scoped ON journal_lines;")
    op.execute("DROP POLICY IF EXISTS fp_select_scoped ON fiscal_periods;")
    op.execute("DROP POLICY IF EXISTS fy_select_scoped ON fiscal_years;")
    op.execute("DROP POLICY IF EXISTS coa_modify_finance ON chart_of_accounts;")
    op.execute("DROP POLICY IF EXISTS coa_select_scoped ON chart_of_accounts;")
    op.execute("DROP FUNCTION IF EXISTS fn_reverse_journal_entry(UUID, DATE, TEXT);")
    op.execute("DROP FUNCTION IF EXISTS fn_post_journal_entry(UUID);")
    op.execute("DROP FUNCTION IF EXISTS fn_create_journal_entry(UUID, DATE, TEXT, CHAR(3), JSONB);")
