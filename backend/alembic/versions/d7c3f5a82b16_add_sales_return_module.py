"""Add Modul 4A: Sales Return / Credit Note

Revision ID: d7c3f5a82b16
Revises: b5f8a2c91e73
Create Date: 2026-08-31

Tables (2): sales_returns, sales_return_lines.
ALTER entity_gl_defaults: + gl_sales_return_account_id (nullable,
falls back to gl_sales_revenue_account_id per PRD edge #5).

RPC (1): fn_approve_sales_return — validate qty vs invoice lines,
receive stock back, compute tax rate from the original invoice,
post credit-note GL (Dr Sales Return / Dr PPN / Cr AR, plus
Dr Inventory / Cr COGS reversal per item), reduce AR outstanding.

Notes vs PRD:
- auth.uid() -> fn_current_user_id(); guards (role + entity) moved
  INTO the RPC like Modules 2-4.
- `SET status = CASE ...` on ar_invoices gets an explicit
  ::ar_invoice_status_enum cast (CASE of literals resolves to text
  and would raise DatatypeMismatchError otherwise).
"""

from alembic import op

revision = "d7c3f5a82b16"
down_revision = "b5f8a2c91e73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enum + entity_gl_defaults column
    # ------------------------------------------------------------------
    op.execute(
        "CREATE TYPE sales_return_status_enum AS ENUM "
        "('DRAFT','APPROVED','CANCELLED')"
    )
    op.execute(
        "ALTER TABLE entity_gl_defaults ADD COLUMN IF NOT EXISTS "
        "gl_sales_return_account_id UUID REFERENCES chart_of_accounts(id)"
    )

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE sales_returns (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          customer_id UUID NOT NULL REFERENCES customers(id),
          ar_invoice_id UUID NOT NULL REFERENCES ar_invoices(id),
          warehouse_id UUID NOT NULL REFERENCES warehouses(id),
          return_number VARCHAR(30) NOT NULL,
          return_date DATE NOT NULL,
          status sales_return_status_enum NOT NULL DEFAULT 'DRAFT',
          reason TEXT NOT NULL,
          subtotal NUMERIC(18,2) NOT NULL DEFAULT 0,
          tax_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
          total_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
          journal_entry_id UUID REFERENCES journal_entries(id),
          created_by UUID NOT NULL REFERENCES user_profiles(id),
          approved_by UUID REFERENCES user_profiles(id),
          approved_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entity_id, return_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sales_return_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          sales_return_id UUID NOT NULL REFERENCES sales_returns(id)
            ON DELETE CASCADE,
          ar_invoice_line_id UUID NOT NULL REFERENCES ar_invoice_lines(id),
          item_id UUID NOT NULL REFERENCES items(id),
          qty_returned NUMERIC(18,4) NOT NULL CHECK (qty_returned > 0),
          unit_price NUMERIC(18,2) NOT NULL,
          line_total NUMERIC(18,2) NOT NULL
        )
        """
    )

    # ------------------------------------------------------------------
    # RLS
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE sales_returns ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY sr_entity_policy ON sales_returns FOR ALL USING (
          entity_id = fn_current_entity_id()
        )
        """
    )
    op.execute("ALTER TABLE sales_return_lines ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY srl_select_policy ON sales_return_lines FOR SELECT
        USING (
          EXISTS (
            SELECT 1 FROM sales_returns sr
            WHERE sr.id = sales_return_lines.sales_return_id
              AND sr.entity_id = fn_current_entity_id()
          )
        )
        """
    )
    op.execute(
        "REVOKE UPDATE, DELETE ON sales_returns FROM PUBLIC"
    )

    # ------------------------------------------------------------------
    # RPC: fn_approve_sales_return
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_approve_sales_return(
          p_sales_return_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_ret           sales_returns%ROWTYPE;
          v_line          RECORD;
          v_invoice       ar_invoices%ROWTYPE;
          v_subtotal      NUMERIC(18,2) := 0;
          v_total_cogs    NUMERIC(18,2) := 0;
          v_tax_rate_pct  NUMERIC;
          v_tax_amount    NUMERIC(18,2);
          v_total_amount  NUMERIC(18,2);
          v_line_cost     NUMERIC(18,4);
          v_receive_result JSONB;
          v_je_lines      JSONB;
          v_je_result     JSONB;
        BEGIN
          IF fn_current_role() NOT IN
             ('DEPT_HEAD_SALES','FINANCE_OPERATOR','DEPT_HEAD_FA',
              'SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only sales heads / finance can approve sales returns.');
          END IF;

          SELECT * INTO v_ret FROM sales_returns
          WHERE id = p_sales_return_id FOR UPDATE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('RETURN_NOT_FOUND',
              'Sales return tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_ret.entity_id THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only approve returns of your own entity.');
          END IF;
          IF v_ret.status <> 'DRAFT' THEN
            PERFORM fn_raise_error('RETURN_INVALID_STATUS',
              format('Sales return berstatus %s, hanya DRAFT yang '
                     'dapat di-approve.', v_ret.status));
          END IF;

          SELECT * INTO v_invoice FROM ar_invoices
          WHERE id = v_ret.ar_invoice_id;
          IF v_invoice.status = 'VOID' THEN
            PERFORM fn_raise_error('INVOICE_VOID',
              'Invoice sudah VOID, tidak bisa diretur.');
          END IF;

          -- Derive the original tax rate from the invoice.
          v_tax_rate_pct := CASE WHEN v_invoice.subtotal > 0
            THEN ROUND(v_invoice.tax_amount / v_invoice.subtotal * 100, 2)
            ELSE 0 END;

          FOR v_line IN
            SELECT * FROM sales_return_lines
            WHERE sales_return_id = p_sales_return_id
          LOOP
            IF v_line.qty_returned > (
              SELECT ail.qty FROM ar_invoice_lines ail
              WHERE ail.id = v_line.ar_invoice_line_id
            ) THEN
              PERFORM fn_raise_error('RETURN_QTY_EXCEEDS_INVOICE',
                format('Qty retur (%s) melebihi qty invoice untuk '
                       'item %s.', v_line.qty_returned, v_line.item_id));
            END IF;

            -- REVIEW FIX: stock must be received back at its COST BASIS
            -- (the avg_cost that was in effect when the goods were sold),
            -- not the invoice price. Receiving at retail price would
            -- capitalize the sales margin into inventory (overstated
            -- assets) and pollute avg_cost for the COGS reversal below.
            -- Receiving at the same avg_cost keeps avg_cost invariant.
            v_line_cost := COALESCE(
              (SELECT avg_cost FROM item_warehouse_stock
               WHERE item_id = v_line.item_id
                 AND warehouse_id = v_ret.warehouse_id),
              v_line.unit_price);

            -- Stock back into the warehouse (reversal of the issue).
            v_receive_result := fn_receive_stock(
              v_line.item_id, v_ret.warehouse_id, v_line.qty_returned,
              v_line_cost, 'SALES_RETURN', p_sales_return_id, NULL);

            v_subtotal := v_subtotal + v_line.line_total;
            v_total_cogs := v_total_cogs
              + ROUND(v_line.qty_returned * v_line_cost, 2);
          END LOOP;

          v_tax_amount := ROUND(v_subtotal * v_tax_rate_pct / 100, 2);
          v_total_amount := v_subtotal + v_tax_amount;

          UPDATE sales_returns SET
            subtotal = v_subtotal, tax_amount = v_tax_amount,
            total_amount = v_total_amount,
            status = 'APPROVED', approved_by = fn_current_user_id(),
            approved_at = now()
          WHERE id = p_sales_return_id;

          -- Credit-note GL: Dr Sales Return (contra-revenue),
          -- Dr PPN Keluaran, Cr AR; plus Dr Inventory / Cr COGS
          -- reversal per item.
          v_je_lines := jsonb_build_array(
            jsonb_build_object('account_id',
              COALESCE(
                (SELECT gl_sales_return_account_id
                 FROM entity_gl_defaults WHERE entity_id = v_ret.entity_id),
                (SELECT gl_sales_revenue_account_id
                 FROM entity_gl_defaults WHERE entity_id = v_ret.entity_id)),
              'debit_amount', v_subtotal, 'credit_amount', 0),
            jsonb_build_object('account_id',
              (SELECT gl_ppn_keluaran_account_id FROM entity_gl_defaults
               WHERE entity_id = v_ret.entity_id),
              'debit_amount', v_tax_amount, 'credit_amount', 0),
            jsonb_build_object('account_id',
              (SELECT gl_ar_account_id FROM entity_gl_defaults
               WHERE entity_id = v_ret.entity_id),
              'debit_amount', 0, 'credit_amount', v_total_amount)
          );

          FOR v_line IN
            SELECT srl.item_id, i.gl_inventory_account_id,
                   i.gl_cogs_account_id,
                   ROUND(srl.qty_returned * COALESCE(
                     (SELECT avg_cost FROM item_warehouse_stock
                      WHERE item_id = srl.item_id
                        AND warehouse_id = v_ret.warehouse_id),
                     srl.unit_price), 2) AS cogs_amount
            FROM sales_return_lines srl
            JOIN items i ON i.id = srl.item_id
            WHERE srl.sales_return_id = p_sales_return_id
          LOOP
            IF v_line.gl_inventory_account_id IS NULL
               OR v_line.gl_cogs_account_id IS NULL THEN
              PERFORM fn_raise_error('ITEM_COGS_ACCOUNT_MISSING',
                format('Item %s belum punya gl_cogs_account_id / '
                       'gl_inventory_account_id.', v_line.item_id));
            END IF;
            IF v_line.cogs_amount > 0 THEN
              v_je_lines := v_je_lines
                || jsonb_build_object('account_id',
                     v_line.gl_inventory_account_id,
                     'debit_amount', v_line.cogs_amount,
                     'credit_amount', 0)
                || jsonb_build_object('account_id',
                     v_line.gl_cogs_account_id,
                     'debit_amount', 0,
                     'credit_amount', v_line.cogs_amount);
            END IF;
          END LOOP;

          v_je_result := fn_create_journal_entry(
            v_ret.entity_id, v_ret.return_date,
            format('Sales Return / Credit Note %s', v_ret.return_number),
            'IDR', v_je_lines);
          PERFORM fn_post_journal_entry(
            (v_je_result->>'journal_entry_id')::uuid);

          UPDATE sales_returns
          SET journal_entry_id = (v_je_result->>'journal_entry_id')::uuid
          WHERE id = p_sales_return_id;

          -- Cut the AR outstanding by the credit-note amount.
          UPDATE ar_invoices SET
            paid_amount = paid_amount + v_total_amount,
            status = (CASE
              WHEN paid_amount + v_total_amount >= total_amount
              THEN 'PAID' ELSE status
            END)::ar_invoice_status_enum
          WHERE id = v_ret.ar_invoice_id;

          INSERT INTO system_logs
            (actor_id, entity_id, action, table_name, record_id, after_data)
          VALUES (fn_current_user_id(), v_ret.entity_id, 'APPROVE',
            'sales_returns', p_sales_return_id::text,
            jsonb_build_object('return_number', v_ret.return_number,
              'total_amount', v_total_amount));

          RETURN jsonb_build_object('success', TRUE,
            'sales_return_id', p_sales_return_id,
            'return_number', v_ret.return_number,
            'total_amount', v_total_amount,
            'cogs_reversed', v_total_cogs);
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS fn_approve_sales_return(UUID)")
    op.execute("DROP TABLE IF EXISTS sales_return_lines CASCADE")
    op.execute("DROP TABLE IF EXISTS sales_returns CASCADE")
    op.execute(
        "ALTER TABLE entity_gl_defaults DROP COLUMN IF EXISTS "
        "gl_sales_return_account_id"
    )
    op.execute("DROP TYPE IF EXISTS sales_return_status_enum")
