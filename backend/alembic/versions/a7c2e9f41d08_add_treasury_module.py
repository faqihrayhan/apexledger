"""Add Modul 6: Treasury & Cash Management

Revision ID: a7c2e9f41d08
Revises: f3a5c7d91b42
Create Date: 2026-08-31

Tables: bank_accounts, petty_cash_funds, kasbon_requests,
kasbon_settlements + lines, bank_statement_lines,
cash_flow_forecast_lines.

Dynamic Approval Engine (approval_thresholds + DIREKSI role +
fn_get_required_approval_role) already deployed with Modul 5.

Adaptasi dialek lokal: auth.uid() -> fn_current_user_id().
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7c2e9f41d08"
down_revision = "f3a5c7d91b42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enums (approval_doc_type_enum + DIREKSI exist from Modul 5)
    # ------------------------------------------------------------------
    op.execute(
        "CREATE TYPE kasbon_status_enum AS ENUM "
        "('DRAFT','PENDING_APPROVAL','APPROVED','REJECTED',"
        "'DISBURSED','SETTLED')"
    )
    op.execute(
        "CREATE TYPE settlement_status_enum AS ENUM "
        "('DRAFT','SUBMITTED','APPROVED')"
    )

    # ------------------------------------------------------------------
    # bank_accounts
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE bank_accounts (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          bank_name VARCHAR(100) NOT NULL,
          account_number VARCHAR(30) NOT NULL,
          account_name VARCHAR(150) NOT NULL,
          currency_code CHAR(3) NOT NULL DEFAULT 'IDR',
          gl_account_id UUID NOT NULL REFERENCES chart_of_accounts(id),
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          UNIQUE (entity_id, account_number)
        )
        """
    )
    op.execute(
        "ALTER TABLE bank_accounts ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY bank_accounts_select_scoped
        ON bank_accounts FOR SELECT USING (
          entity_id = fn_current_entity_id()
          OR fn_current_role() IN ('SUPER_ADMIN','IT_ADMIN')
        )
        """
    )
    op.execute(
        """
        CREATE POLICY bank_accounts_insert_scoped
        ON bank_accounts FOR INSERT WITH CHECK (
          entity_id = fn_current_entity_id()
          AND fn_current_role() IN (
            'DEPT_HEAD_FA','FINANCE_OPERATOR','SUPER_ADMIN')
        )
        """
    )


    # ------------------------------------------------------------------
    # petty_cash_funds
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE petty_cash_funds (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          department_code VARCHAR(30),
          custodian_user_id UUID NOT NULL
            REFERENCES user_profiles(id),
          fund_limit NUMERIC(18,2) NOT NULL,
          current_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
          gl_account_id UUID NOT NULL REFERENCES chart_of_accounts(id)
        )
        """
    )
    op.execute(
        "ALTER TABLE petty_cash_funds ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY pcf_select_scoped ON petty_cash_funds
        FOR SELECT USING (
          entity_id = fn_current_entity_id()
          OR fn_current_role() IN ('SUPER_ADMIN','IT_ADMIN')
        )
        """
    )

    # ------------------------------------------------------------------
    # kasbon_requests
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE kasbon_requests (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          requested_by UUID NOT NULL REFERENCES user_profiles(id),
          department_code VARCHAR(30),
          amount NUMERIC(18,2) NOT NULL CHECK (amount > 0),
          purpose TEXT NOT NULL,
          request_date DATE NOT NULL,
          status kasbon_status_enum NOT NULL DEFAULT 'DRAFT',
          required_approval_role role_enum,
          approved_by UUID REFERENCES user_profiles(id),
          approved_at TIMESTAMPTZ,
          disbursed_journal_entry_id UUID
            REFERENCES journal_entries(id),
          disbursed_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "ALTER TABLE kasbon_requests ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY kasbon_select_scoped ON kasbon_requests
        FOR SELECT USING (
          entity_id = fn_current_entity_id()
          OR fn_current_role() IN ('SUPER_ADMIN','IT_ADMIN')
        )
        """
    )
    op.execute(
        """
        CREATE POLICY kasbon_insert_scoped ON kasbon_requests
        FOR INSERT WITH CHECK (
          entity_id = fn_current_entity_id()
          AND fn_current_role() IN (
            'FINANCE_OPERATOR','DEPT_HEAD_SALES',
            'DEPT_HEAD_WAREHOUSE','DEPT_HEAD_FA','SUPER_ADMIN')
        )
        """
    )
    op.execute(
        "REVOKE UPDATE, DELETE ON kasbon_requests FROM PUBLIC"
    )

    # ------------------------------------------------------------------
    # kasbon_settlements + lines
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE kasbon_settlements (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          kasbon_request_id UUID NOT NULL
            REFERENCES kasbon_requests(id),
          settlement_date DATE NOT NULL,
          actual_amount_used NUMERIC(18,2) NOT NULL
            CHECK (actual_amount_used >= 0),
          refund_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
          additional_claim_amount NUMERIC(18,2)
            NOT NULL DEFAULT 0,
          status settlement_status_enum NOT NULL DEFAULT 'DRAFT',
          journal_entry_id UUID REFERENCES journal_entries(id),
          UNIQUE (kasbon_request_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE kasbon_settlement_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          kasbon_settlement_id UUID NOT NULL
            REFERENCES kasbon_settlements(id) ON DELETE CASCADE,
          expense_account_id UUID NOT NULL
            REFERENCES chart_of_accounts(id),
          description VARCHAR(200) NOT NULL,
          amount NUMERIC(18,2) NOT NULL CHECK (amount > 0),
          receipt_reference VARCHAR(50)
        )
        """
    )

    # ------------------------------------------------------------------
    # bank_statement_lines + partial index
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE bank_statement_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          bank_account_id UUID NOT NULL
            REFERENCES bank_accounts(id),
          statement_date DATE NOT NULL,
          description VARCHAR(255),
          amount NUMERIC(18,2) NOT NULL,
          is_matched BOOLEAN NOT NULL DEFAULT FALSE,
          matched_transaction_type VARCHAR(30),
          matched_transaction_id UUID,
          imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_bank_stmt_unmatched "
        "ON bank_statement_lines(bank_account_id, amount) "
        "WHERE is_matched = FALSE"
    )

    # ------------------------------------------------------------------
    # cash_flow_forecast_lines
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE cash_flow_forecast_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          forecast_week_start DATE NOT NULL,
          category VARCHAR(10) NOT NULL
            CHECK (category IN ('INFLOW','OUTFLOW')),
          source_type VARCHAR(30) NOT NULL,
          source_reference_id UUID,
          estimated_amount NUMERIC(18,2) NOT NULL
        )
        """
    )

    # RLS child tables scoped via subquery to parents
    op.execute(
        "ALTER TABLE kasbon_settlements ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY kasbon_settlements_select_scoped
        ON kasbon_settlements FOR SELECT USING (
          kasbon_request_id IN (SELECT id FROM kasbon_requests)
        )
        """
    )
    op.execute(
        "ALTER TABLE kasbon_settlement_lines ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY ksl_select_scoped
        ON kasbon_settlement_lines FOR SELECT USING (
          kasbon_settlement_id IN (
            SELECT id FROM kasbon_settlements)
        )
        """
    )
    op.execute(
        "ALTER TABLE bank_statement_lines ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY bsl_select_scoped
        ON bank_statement_lines FOR SELECT USING (
          bank_account_id IN (SELECT id FROM bank_accounts)
        )
        """
    )
    op.execute(
        "ALTER TABLE cash_flow_forecast_lines ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY cffl_select_scoped
        ON cash_flow_forecast_lines FOR SELECT USING (
          entity_id = fn_current_entity_id()
          OR fn_current_role() IN ('SUPER_ADMIN','IT_ADMIN')
        )
        """
    )
    op.execute(
        "REVOKE UPDATE, DELETE ON bank_statement_lines FROM PUBLIC"
    )

    # ------------------------------------------------------------------
    # RPC 1: fn_submit_kasbon_request
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_submit_kasbon_request(
            p_kasbon_request_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql
        SECURITY DEFINER AS $$
        DECLARE
            v_kasbon        kasbon_requests%ROWTYPE;
            v_required_role role_enum;
        BEGIN
            SELECT * INTO v_kasbon FROM kasbon_requests
              WHERE id = p_kasbon_request_id FOR UPDATE;
            IF NOT FOUND THEN
                PERFORM fn_raise_error('KASBON_NOT_FOUND',
                    'Kasbon tidak ditemukan.');
            END IF;
            IF v_kasbon.status <> 'DRAFT' THEN
                PERFORM fn_raise_error('KASBON_INVALID_STATUS',
                    format('Kasbon berstatus %s, '
                           'tidak bisa disubmit.',
                           v_kasbon.status));
            END IF;

            v_required_role := fn_get_required_approval_role(
                v_kasbon.entity_id, 'KASBON', v_kasbon.amount);

            UPDATE kasbon_requests SET
                status = 'PENDING_APPROVAL',
                required_approval_role = v_required_role
            WHERE id = p_kasbon_request_id;

            RETURN jsonb_build_object(
                'kasbon_request_id', p_kasbon_request_id,
                'required_approval_role', v_required_role);
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 2: fn_approve_kasbon_request
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_approve_kasbon_request(
            p_kasbon_request_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql
        SECURITY DEFINER AS $$
        DECLARE
            v_kasbon kasbon_requests%ROWTYPE;
        BEGIN
            SELECT * INTO v_kasbon FROM kasbon_requests
              WHERE id = p_kasbon_request_id FOR UPDATE;
            IF NOT FOUND THEN
                PERFORM fn_raise_error('KASBON_NOT_FOUND',
                    'Kasbon tidak ditemukan.');
            END IF;
            IF v_kasbon.status <> 'PENDING_APPROVAL' THEN
                PERFORM fn_raise_error('KASBON_INVALID_STATUS',
                    format('Kasbon berstatus %s, '
                           'tidak bisa diapprove.',
                           v_kasbon.status));
            END IF;
            IF fn_current_role() NOT IN (
                v_kasbon.required_approval_role, 'SUPER_ADMIN')
            THEN
                PERFORM fn_raise_error(
                    'INSUFFICIENT_APPROVAL_AUTHORITY',
                    format('Kasbon sebesar Rp%s memerlukan '
                           'otorisasi %s.',
                           v_kasbon.amount,
                           v_kasbon.required_approval_role));
            END IF;

            UPDATE kasbon_requests SET
                status = 'APPROVED',
                approved_by = fn_current_user_id(),
                approved_at = now()
            WHERE id = p_kasbon_request_id;

            INSERT INTO system_logs(
                actor_id, entity_id, action, table_name,
                record_id, after_data)
            VALUES (
                fn_current_user_id(), v_kasbon.entity_id,
                'APPROVE', 'kasbon_requests',
                p_kasbon_request_id::text,
                jsonb_build_object('status', 'APPROVED',
                    'approver_role', fn_current_role()));

            RETURN jsonb_build_object(
                'kasbon_request_id', p_kasbon_request_id,
                'status', 'APPROVED');
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 3: fn_disburse_kasbon
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_disburse_kasbon(
            p_kasbon_request_id UUID,
            p_bank_account_id UUID,
            p_piutang_karyawan_account_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql
        SECURITY DEFINER AS $$
        DECLARE
            v_kasbon   kasbon_requests%ROWTYPE;
            v_je_result JSONB;
        BEGIN
            SELECT * INTO v_kasbon FROM kasbon_requests
              WHERE id = p_kasbon_request_id FOR UPDATE;
            IF NOT FOUND THEN
                PERFORM fn_raise_error('KASBON_NOT_FOUND',
                    'Kasbon tidak ditemukan.');
            END IF;
            IF v_kasbon.status <> 'APPROVED' THEN
                PERFORM fn_raise_error('KASBON_NOT_APPROVED',
                    'Disbursement hanya bisa dilakukan setelah '
                    'kasbon APPROVED.');
            END IF;

            v_je_result := fn_create_journal_entry(
                v_kasbon.entity_id, CURRENT_DATE,
                format('Kasbon Disbursement — %s',
                       v_kasbon.purpose), 'IDR',
                jsonb_build_array(
                    jsonb_build_object(
                        'account_id',
                        p_piutang_karyawan_account_id,
                        'debit_amount', v_kasbon.amount,
                        'credit_amount', 0),
                    jsonb_build_object(
                        'account_id',
                        (SELECT gl_account_id FROM bank_accounts
                         WHERE id = p_bank_account_id),
                        'debit_amount', 0,
                        'credit_amount', v_kasbon.amount)
                ));
            PERFORM fn_post_journal_entry(
                (v_je_result->>'journal_entry_id')::uuid);

            UPDATE kasbon_requests SET
                status = 'DISBURSED',
                disbursed_journal_entry_id =
                    (v_je_result->>'journal_entry_id')::uuid,
                disbursed_at = now()
            WHERE id = p_kasbon_request_id;

            RETURN jsonb_build_object(
                'kasbon_request_id', p_kasbon_request_id,
                'journal_entry_id',
                  (v_je_result->>'journal_entry_id')::uuid);
        END;
        $$;
        """
    )


    # ------------------------------------------------------------------
    # RPC 4: fn_settle_kasbon
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_settle_kasbon(
            p_kasbon_request_id UUID,
            p_settlement_date DATE,
            p_lines JSONB,
            p_piutang_karyawan_account_id UUID,
            p_bank_account_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql
        SECURITY DEFINER AS $$
        DECLARE
            v_kasbon       kasbon_requests%ROWTYPE;
            v_actual_used  NUMERIC(18,2) := 0;
            v_refund       NUMERIC(18,2) := 0;
            v_additional   NUMERIC(18,2) := 0;
            v_line         JSONB;
            v_je_lines     JSONB := '[]'::jsonb;
            v_je_result    JSONB;
            v_settlement_id UUID;
        BEGIN
            SELECT * INTO v_kasbon FROM kasbon_requests
              WHERE id = p_kasbon_request_id FOR UPDATE;
            IF NOT FOUND THEN
                PERFORM fn_raise_error('KASBON_NOT_FOUND',
                    'Kasbon tidak ditemukan.');
            END IF;
            IF v_kasbon.status <> 'DISBURSED' THEN
                PERFORM fn_raise_error('KASBON_NOT_DISBURSED',
                    'Settlement hanya untuk kasbon DISBURSED.');
            END IF;
            IF EXISTS (
                SELECT 1 FROM kasbon_settlements
                WHERE kasbon_request_id = p_kasbon_request_id)
            THEN
                PERFORM fn_raise_error('KASBON_ALREADY_SETTLED',
                    'Kasbon ini sudah pernah disettle.');
            END IF;

            FOR v_line IN
              SELECT * FROM jsonb_array_elements(p_lines) l
            LOOP
                v_actual_used := v_actual_used
                    + (v_line->>'amount')::numeric;
                v_je_lines := v_je_lines || jsonb_build_object(
                    'account_id',
                      (v_line->>'expense_account_id')::uuid,
                    'debit_amount', (v_line->>'amount')::numeric,
                    'credit_amount', 0);
            END LOOP;

            IF v_actual_used < v_kasbon.amount THEN
                v_refund := v_kasbon.amount - v_actual_used;
            ELSIF v_actual_used > v_kasbon.amount THEN
                v_additional :=
                    v_actual_used - v_kasbon.amount;
            END IF;

            INSERT INTO kasbon_settlements (
                kasbon_request_id, settlement_date,
                actual_amount_used, refund_amount,
                additional_claim_amount, status)
            VALUES (
                p_kasbon_request_id, p_settlement_date,
                v_actual_used, v_refund, v_additional,
                'APPROVED')
            RETURNING id INTO v_settlement_id;

            INSERT INTO kasbon_settlement_lines (
                kasbon_settlement_id, expense_account_id,
                description, amount, receipt_reference)
            SELECT v_settlement_id,
                (l->>'expense_account_id')::uuid,
                l->>'description',
                (l->>'amount')::numeric,
                l->>'receipt_reference'
            FROM jsonb_array_elements(p_lines) l;

            -- Kredit Piutang Karyawan full (clear ke 0).
            v_je_lines := v_je_lines || jsonb_build_object(
                'account_id', p_piutang_karyawan_account_id,
                'debit_amount', 0,
                'credit_amount', v_kasbon.amount);

            IF v_refund > 0 THEN
                -- Karyawan kembalikan sisa ke bank.
                v_je_lines := v_je_lines || jsonb_build_object(
                    'account_id',
                    (SELECT gl_account_id FROM bank_accounts
                     WHERE id = p_bank_account_id),
                    'debit_amount', v_refund,
                    'credit_amount', 0);
            ELSIF v_additional > 0 THEN
                -- Perusahaan reimburse kelebihan.
                v_je_lines := v_je_lines || jsonb_build_object(
                    'account_id',
                    (SELECT gl_account_id FROM bank_accounts
                     WHERE id = p_bank_account_id),
                    'debit_amount', 0,
                    'credit_amount', v_additional);
            END IF;

            v_je_result := fn_create_journal_entry(
                v_kasbon.entity_id, p_settlement_date,
                format('Kasbon Settlement — %s',
                       v_kasbon.purpose), 'IDR', v_je_lines);
            PERFORM fn_post_journal_entry(
                (v_je_result->>'journal_entry_id')::uuid);

            UPDATE kasbon_settlements
              SET journal_entry_id =
                    (v_je_result->>'journal_entry_id')::uuid
              WHERE id = v_settlement_id;
            UPDATE kasbon_requests SET status = 'SETTLED'
              WHERE id = p_kasbon_request_id;

            RETURN jsonb_build_object(
                'settlement_id', v_settlement_id,
                'actual_used', v_actual_used,
                'refund', v_refund,
                'additional_claim', v_additional,
                'journal_entry_id',
                  (v_je_result->>'journal_entry_id')::uuid);
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 5: fn_auto_match_bank_statement
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_auto_match_bank_statement(
            p_bank_account_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql
        SECURITY DEFINER AS $$
        DECLARE
            v_line          RECORD;
            v_matched_count INT := 0;
            v_ar_match      RECORD;
            v_ap_match      RECORD;
        BEGIN
            FOR v_line IN
              SELECT * FROM bank_statement_lines
              WHERE bank_account_id = p_bank_account_id
                AND is_matched = FALSE
            LOOP
                IF v_line.amount > 0 THEN
                    SELECT id INTO v_ar_match FROM ar_payments
                    WHERE amount = v_line.amount
                      AND payment_date BETWEEN
                            v_line.statement_date - 3
                        AND v_line.statement_date + 3
                      AND id NOT IN (
                        SELECT matched_transaction_id
                        FROM bank_statement_lines
                        WHERE matched_transaction_id
                              IS NOT NULL)
                    LIMIT 1;
                    IF v_ar_match.id IS NOT NULL THEN
                        UPDATE bank_statement_lines SET
                          is_matched = TRUE,
                          matched_transaction_type = 'AR_PAYMENT',
                          matched_transaction_id = v_ar_match.id
                        WHERE id = v_line.id;
                        v_matched_count :=
                            v_matched_count + 1;
                    END IF;
                ELSE
                    SELECT id INTO v_ap_match FROM ap_payments
                    WHERE amount = ABS(v_line.amount)
                      AND payment_date BETWEEN
                            v_line.statement_date - 3
                        AND v_line.statement_date + 3
                      AND id NOT IN (
                        SELECT matched_transaction_id
                        FROM bank_statement_lines
                        WHERE matched_transaction_id
                              IS NOT NULL)
                    LIMIT 1;
                    IF v_ap_match.id IS NOT NULL THEN
                        UPDATE bank_statement_lines SET
                          is_matched = TRUE,
                          matched_transaction_type = 'AP_PAYMENT',
                          matched_transaction_id = v_ap_match.id
                        WHERE id = v_line.id;
                        v_matched_count :=
                            v_matched_count + 1;
                    END IF;
                END IF;
            END LOOP;

            RETURN jsonb_build_object(
                'matched_count', v_matched_count);
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 6: fn_get_cash_flow_forecast
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_get_cash_flow_forecast(
            p_entity_id UUID,
            p_weeks_ahead INT DEFAULT 4
        ) RETURNS TABLE (
            week_start DATE,
            category VARCHAR,
            source_type VARCHAR,
            estimated_amount NUMERIC
        ) LANGUAGE plpgsql STABLE AS $$
        BEGIN
            RETURN QUERY
            SELECT date_trunc('week', ai.due_date)::date,
                   'INFLOW'::varchar, 'AR_DUE'::varchar,
                   SUM(ai.total_amount - ai.paid_amount)
            FROM ar_invoices ai
            WHERE ai.entity_id = p_entity_id
              AND ai.status IN ('ISSUED','PARTIALLY_PAID')
              AND ai.due_date BETWEEN CURRENT_DATE
                  AND CURRENT_DATE + (p_weeks_ahead * 7)
            GROUP BY 1
            UNION ALL
            SELECT date_trunc('week', ab.due_date)::date,
                   'OUTFLOW'::varchar, 'AP_DUE'::varchar,
                   SUM(ab.total_amount - ab.paid_amount)
            FROM ap_bills ab
            WHERE ab.entity_id = p_entity_id
              AND ab.status IN ('APPROVED')
              AND ab.due_date BETWEEN CURRENT_DATE
                  AND CURRENT_DATE + (p_weeks_ahead * 7)
            GROUP BY 1
            UNION ALL
            SELECT date_trunc('week', kr.request_date)::date,
                   'OUTFLOW'::varchar, 'KASBON_PENDING'::varchar,
                   SUM(kr.amount)
            FROM kasbon_requests kr
            WHERE kr.entity_id = p_entity_id
              AND kr.status IN ('APPROVED','PENDING_APPROVAL')
            GROUP BY 1
            ORDER BY 1;
        END;
        $$;
        """
    )

    # --- end of Modul 6 migration ---



    # Tables complete; RPC part 3 follows



def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS pcf_select_scoped "
        "ON petty_cash_funds"
    )
    op.execute("DROP TABLE IF EXISTS petty_cash_funds")
    op.execute(
        "DROP POLICY IF EXISTS bank_accounts_insert_scoped "
        "ON bank_accounts"
    )
    op.execute(
        "DROP POLICY IF EXISTS bank_accounts_select_scoped "
        "ON bank_accounts"
    )
    op.execute("DROP TABLE IF EXISTS bank_accounts")
    op.execute("DROP TYPE IF EXISTS settlement_status_enum")
    op.execute("DROP TYPE IF EXISTS kasbon_status_enum")
