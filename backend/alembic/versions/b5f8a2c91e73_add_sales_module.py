"""Add Modul 4: Omnichannel Sales & AR

Revision ID: b5f8a2c91e73
Revises: c3a7e9f01d42
Create Date: 2026-08-31

Tables (11): entity_gl_defaults, customers, sales_orders,
sales_order_lines, delivery_orders, delivery_order_lines,
ar_invoices, ar_invoice_lines, ar_payments, ar_payment_allocations,
pos_transactions, pos_transaction_lines.

RPCs (6): fn_check_credit_limit, fn_confirm_sales_order,
fn_create_delivery_order (issues stock per line), fn_issue_ar_invoice
(3-way match DO vs SO, GL sales + COGS per item),
fn_record_ar_payment (allocation FIFO/explicit, GL cash receipt),
fn_process_pos_sale (fast path, GL batched separately),
fn_post_pos_batch_journal (shift/daily aggregate posting).

Adaptations vs PRD (Supabase -> local):
- auth.uid() -> fn_current_user_id()
- auth.users -> user_profiles
- role guards moved INTO the RPCs (defense-in-depth, mirroring
  Modules 2/3) instead of API-layer only.
"""

from alembic import op

revision = "b5f8a2c91e73"
down_revision = "c3a7e9f01d42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enums
    # ------------------------------------------------------------------
    op.execute(
        "CREATE TYPE so_status_enum AS ENUM "
        "('DRAFT','CONFIRMED','PARTIALLY_DELIVERED','DELIVERED','CANCELLED')"
    )
    op.execute("CREATE TYPE do_status_enum AS ENUM ('DRAFT','DELIVERED','INVOICED')")
    op.execute(
        "CREATE TYPE ar_invoice_status_enum AS ENUM "
        "('DRAFT','ISSUED','PARTIALLY_PAID','PAID','VOID')"
    )

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE entity_gl_defaults (
          entity_id UUID PRIMARY KEY REFERENCES entities(id),
          gl_ar_account_id UUID NOT NULL REFERENCES chart_of_accounts(id),
          gl_sales_revenue_account_id UUID NOT NULL REFERENCES chart_of_accounts(id),
          gl_ppn_keluaran_account_id UUID NOT NULL REFERENCES chart_of_accounts(id),
          gl_kas_bank_default_account_id UUID NOT NULL REFERENCES chart_of_accounts(id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE customers (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          customer_code VARCHAR(20) NOT NULL,
          customer_name VARCHAR(150) NOT NULL,
          credit_limit NUMERIC(18,2) NOT NULL DEFAULT 0,
          payment_term_days SMALLINT NOT NULL DEFAULT 30,
          npwp VARCHAR(20),
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entity_id, customer_code)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sales_orders (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          customer_id UUID NOT NULL REFERENCES customers(id),
          warehouse_id UUID NOT NULL REFERENCES warehouses(id),
          so_number VARCHAR(30) NOT NULL,
          order_date DATE NOT NULL,
          status so_status_enum NOT NULL DEFAULT 'DRAFT',
          total_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
          created_by UUID NOT NULL REFERENCES user_profiles(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entity_id, so_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sales_order_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          sales_order_id UUID NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
          item_id UUID NOT NULL REFERENCES items(id),
          qty_ordered NUMERIC(18,4) NOT NULL CHECK (qty_ordered > 0),
          qty_delivered NUMERIC(18,4) NOT NULL DEFAULT 0,
          unit_price NUMERIC(18,2) NOT NULL CHECK (unit_price >= 0),
          line_total NUMERIC(18,2) NOT NULL,
          CONSTRAINT chk_delivered_not_exceed
            CHECK (qty_delivered <= qty_ordered)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE delivery_orders (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          sales_order_id UUID NOT NULL REFERENCES sales_orders(id),
          warehouse_id UUID NOT NULL REFERENCES warehouses(id),
          do_number VARCHAR(30) NOT NULL,
          delivery_date DATE NOT NULL,
          status do_status_enum NOT NULL DEFAULT 'DRAFT',
          created_by UUID NOT NULL REFERENCES user_profiles(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entity_id, do_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE delivery_order_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          delivery_order_id UUID NOT NULL REFERENCES delivery_orders(id) ON DELETE CASCADE,
          sales_order_line_id UUID NOT NULL REFERENCES sales_order_lines(id),
          item_id UUID NOT NULL REFERENCES items(id),
          qty_delivered NUMERIC(18,4) NOT NULL CHECK (qty_delivered > 0),
          unit_cost NUMERIC(18,4) NOT NULL DEFAULT 0,
          total_cost NUMERIC(18,2) NOT NULL DEFAULT 0
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ar_invoices (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          customer_id UUID NOT NULL REFERENCES customers(id),
          delivery_order_id UUID REFERENCES delivery_orders(id),
          invoice_number VARCHAR(30) NOT NULL,
          invoice_date DATE NOT NULL,
          due_date DATE NOT NULL,
          status ar_invoice_status_enum NOT NULL DEFAULT 'DRAFT',
          subtotal NUMERIC(18,2) NOT NULL DEFAULT 0,
          tax_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
          total_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
          paid_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
          efaktur_number VARCHAR(30),
          journal_entry_id UUID REFERENCES journal_entries(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entity_id, invoice_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ar_invoice_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          ar_invoice_id UUID NOT NULL REFERENCES ar_invoices(id) ON DELETE CASCADE,
          item_id UUID NOT NULL REFERENCES items(id),
          qty NUMERIC(18,4) NOT NULL,
          unit_price NUMERIC(18,2) NOT NULL,
          line_total NUMERIC(18,2) NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ar_payments (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          customer_id UUID NOT NULL REFERENCES customers(id),
          payment_date DATE NOT NULL,
          amount NUMERIC(18,2) NOT NULL CHECK (amount > 0),
          payment_method VARCHAR(20) NOT NULL,
          journal_entry_id UUID REFERENCES journal_entries(id),
          created_by UUID NOT NULL REFERENCES user_profiles(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ar_payment_allocations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          allocation_date DATE NOT NULL DEFAULT CURRENT_DATE,
          ar_payment_id UUID NOT NULL REFERENCES ar_payments(id) ON DELETE CASCADE,
          ar_invoice_id UUID NOT NULL REFERENCES ar_invoices(id),
          allocated_amount NUMERIC(18,2) NOT NULL CHECK (allocated_amount > 0),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE pos_transactions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          warehouse_id UUID NOT NULL REFERENCES warehouses(id),
          transaction_number VARCHAR(30) NOT NULL,
          transaction_date TIMESTAMPTZ NOT NULL DEFAULT now(),
          total_amount NUMERIC(18,2) NOT NULL,
          payment_method VARCHAR(20) NOT NULL,
          cashier_id UUID NOT NULL REFERENCES user_profiles(id),
          is_synced BOOLEAN NOT NULL DEFAULT TRUE,
          journal_entry_id UUID REFERENCES journal_entries(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entity_id, transaction_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE pos_transaction_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          pos_transaction_id UUID NOT NULL REFERENCES pos_transactions(id) ON DELETE CASCADE,
          item_id UUID NOT NULL REFERENCES items(id),
          qty NUMERIC(18,4) NOT NULL,
          unit_price NUMERIC(18,2) NOT NULL,
          line_total NUMERIC(18,2) NOT NULL
        )
        """
    )

    # ------------------------------------------------------------------
    # RLS — entity-scoped policies for the sales tables.
    # ------------------------------------------------------------------
    for table in (
        "entity_gl_defaults", "customers", "sales_orders",
        "delivery_orders", "ar_invoices", "ar_payments",
        "pos_transactions",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY entity_defaults_policy ON entity_gl_defaults FOR ALL
        USING (entity_id = fn_current_entity_id())
        """
    )
    op.execute(
        """
        CREATE POLICY customers_entity_policy ON customers FOR ALL
        USING (entity_id = fn_current_entity_id())
        """
    )
    op.execute(
        """
        CREATE POLICY so_entity_policy ON sales_orders FOR ALL
        USING (entity_id = fn_current_entity_id())
        """
    )
    op.execute(
        """
        CREATE POLICY do_entity_policy ON delivery_orders FOR ALL
        USING (entity_id = fn_current_entity_id())
        """
    )
    op.execute(
        """
        CREATE POLICY ar_invoice_entity_policy ON ar_invoices FOR ALL
        USING (entity_id = fn_current_entity_id())
        """
    )
    op.execute(
        """
        CREATE POLICY ar_payment_entity_policy ON ar_payments FOR ALL
        USING (entity_id = fn_current_entity_id())
        """
    )
    op.execute(
        """
        CREATE POLICY pos_txn_entity_policy ON pos_transactions FOR ALL
        USING (entity_id = fn_current_entity_id())
        """
    )
    op.execute(
        "REVOKE UPDATE, DELETE ON ar_invoices, pos_transactions FROM PUBLIC"
    )

    # ------------------------------------------------------------------
    # RPC: fn_check_credit_limit
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_check_credit_limit(
          p_customer_id UUID, p_additional_amount NUMERIC
        ) RETURNS BOOLEAN LANGUAGE plpgsql STABLE AS $$
        DECLARE
          v_credit_limit NUMERIC(18,2);
          v_current_ar   NUMERIC(18,2);
        BEGIN
          SELECT credit_limit INTO v_credit_limit
          FROM customers WHERE id = p_customer_id;
          SELECT COALESCE(SUM(total_amount - paid_amount), 0)
          INTO v_current_ar
          FROM ar_invoices
          WHERE customer_id = p_customer_id
            AND status IN ('ISSUED','PARTIALLY_PAID');
          RETURN (v_current_ar + p_additional_amount) <= v_credit_limit;
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC: fn_confirm_sales_order
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_confirm_sales_order(p_sales_order_id UUID)
        RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_so sales_orders%ROWTYPE;
        BEGIN
          IF fn_current_role() NOT IN
             ('SALES_OPERATOR','DEPT_HEAD_SALES','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only sales roles can confirm sales orders.');
          END IF;

          SELECT * INTO v_so FROM sales_orders
          WHERE id = p_sales_order_id FOR UPDATE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('SO_NOT_FOUND', 'Sales order tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_so.entity_id THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only confirm sales orders of your own entity.');
          END IF;
          IF v_so.status <> 'DRAFT' THEN
            PERFORM fn_raise_error('SO_INVALID_STATUS',
              format('Sales order berstatus %s, hanya DRAFT yang dapat '
                     'dikonfirmasi.', v_so.status));
          END IF;

          IF NOT fn_check_credit_limit(v_so.customer_id, v_so.total_amount) THEN
            PERFORM fn_raise_error('CREDIT_LIMIT_EXCEEDED',
              'Order ini melebihi credit limit customer yang tersisa.');
          END IF;

          UPDATE sales_orders SET status = 'CONFIRMED'
          WHERE id = p_sales_order_id;

          INSERT INTO system_logs
            (actor_id, entity_id, action, table_name, record_id, after_data)
          VALUES (fn_current_user_id(), v_so.entity_id, 'CONFIRM',
            'sales_orders', p_sales_order_id::text,
            jsonb_build_object('status', 'CONFIRMED'));

          RETURN jsonb_build_object('success', TRUE,
            'sales_order_id', p_sales_order_id, 'status', 'CONFIRMED');
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC: fn_create_delivery_order
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_create_delivery_order(
          p_sales_order_id UUID, p_delivery_date DATE, p_lines JSONB
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_so           sales_orders%ROWTYPE;
          v_do_id        UUID;
          v_do_number    VARCHAR(30);
          v_line         JSONB;
          v_so_line      sales_order_lines%ROWTYPE;
          v_issue_result JSONB;
          v_all_delivered BOOLEAN;
        BEGIN
          IF fn_current_role() NOT IN
             ('WAREHOUSE_OPERATOR','DEPT_HEAD_WAREHOUSE','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only warehouse roles can create delivery orders.');
          END IF;

          SELECT * INTO v_so FROM sales_orders
          WHERE id = p_sales_order_id FOR UPDATE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('SO_NOT_FOUND', 'Sales order tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_so.entity_id THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only deliver within your own entity.');
          END IF;
          IF v_so.status NOT IN ('CONFIRMED','PARTIALLY_DELIVERED') THEN
            PERFORM fn_raise_error('SO_INVALID_STATUS',
              format('Sales order berstatus %s, tidak bisa dibuatkan '
                     'surat jalan.', v_so.status));
          END IF;

          v_do_number := 'DO-' || to_char(p_delivery_date, 'YYYYMMDD') || '-'
            || substr(gen_random_uuid()::text, 1, 6);
          INSERT INTO delivery_orders
            (entity_id, sales_order_id, warehouse_id, do_number,
             delivery_date, status, created_by)
          VALUES
            (v_so.entity_id, p_sales_order_id, v_so.warehouse_id,
             v_do_number, p_delivery_date, 'DELIVERED', fn_current_user_id())
          RETURNING id INTO v_do_id;

          FOR v_line IN SELECT * FROM jsonb_array_elements(p_lines) LOOP
            SELECT * INTO v_so_line FROM sales_order_lines
            WHERE id = (v_line->>'sales_order_line_id')::uuid FOR UPDATE;

            IF v_so_line.qty_delivered + (v_line->>'qty_delivered')::numeric
                 > v_so_line.qty_ordered THEN
              PERFORM fn_raise_error('DELIVERY_EXCEEDS_ORDER',
                format('Qty delivery melebihi sisa qty ordered untuk '
                       'item %s.', v_so_line.item_id));
            END IF;

            v_issue_result := fn_issue_stock(
              v_so_line.item_id, v_so.warehouse_id,
              (v_line->>'qty_delivered')::numeric,
              'DELIVERY_ORDER', v_do_id);

            INSERT INTO delivery_order_lines
              (delivery_order_id, sales_order_line_id, item_id,
               qty_delivered, unit_cost, total_cost)
            VALUES
              (v_do_id, v_so_line.id, v_so_line.item_id,
               (v_line->>'qty_delivered')::numeric,
               (v_issue_result->>'weighted_unit_cost')::numeric,
               (v_issue_result->>'total_cost')::numeric);

            UPDATE sales_order_lines
            SET qty_delivered = qty_delivered
              + (v_line->>'qty_delivered')::numeric
            WHERE id = v_so_line.id;
          END LOOP;

          SELECT bool_and(qty_delivered = qty_ordered)
          INTO v_all_delivered
          FROM sales_order_lines
          WHERE sales_order_id = p_sales_order_id;

          UPDATE sales_orders
          SET status = (CASE WHEN v_all_delivered
                            THEN 'DELIVERED' ELSE 'PARTIALLY_DELIVERED'
                       END)::so_status_enum
          WHERE id = p_sales_order_id;

          RETURN jsonb_build_object('success', TRUE,
            'delivery_order_id', v_do_id, 'do_number', v_do_number,
            'so_status',
            CASE WHEN v_all_delivered THEN 'DELIVERED'
                 ELSE 'PARTIALLY_DELIVERED' END);
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC: fn_issue_ar_invoice
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_issue_ar_invoice(
          p_delivery_order_id UUID, p_tax_rate_pct NUMERIC DEFAULT 11
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_do            delivery_orders%ROWTYPE;
          v_so            sales_orders%ROWTYPE;
          v_do_line       RECORD;
          v_so_line       sales_order_lines%ROWTYPE;
          v_subtotal      NUMERIC(18,2) := 0;
          v_total_cogs    NUMERIC(18,2) := 0;
          v_tax_amount    NUMERIC(18,2);
          v_total_amount  NUMERIC(18,2);
          v_invoice_id    UUID;
          v_invoice_number VARCHAR(30);
          v_je_lines      JSONB;
          v_cogs_line     RECORD;
          v_je_result     JSONB;
        BEGIN
          IF fn_current_role() NOT IN
             ('FINANCE_OPERATOR','DEPT_HEAD_FA','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only finance roles can issue AR invoices.');
          END IF;

          SELECT * INTO v_do FROM delivery_orders
          WHERE id = p_delivery_order_id FOR UPDATE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('DO_NOT_FOUND', 'Surat jalan tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_do.entity_id THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only invoice within your own entity.');
          END IF;
          IF v_do.status <> 'DELIVERED' THEN
            PERFORM fn_raise_error('DO_INVALID_STATUS',
              format('Surat jalan berstatus %s, tidak bisa difakturkan.',
                     v_do.status));
          END IF;
          IF EXISTS (SELECT 1 FROM ar_invoices
                     WHERE delivery_order_id = p_delivery_order_id) THEN
            PERFORM fn_raise_error('DO_ALREADY_INVOICED',
              'Surat jalan ini sudah pernah difakturkan.');
          END IF;

          SELECT * INTO v_so FROM sales_orders
          WHERE id = v_do.sales_order_id;

          -- 3-way match: every DO line must belong to the parent SO
          -- with matching prices; quantities are already constrained
          -- by qty_delivered <= qty_ordered at DO creation.
          FOR v_do_line IN
            SELECT * FROM delivery_order_lines
            WHERE delivery_order_id = p_delivery_order_id
          LOOP
            SELECT * INTO v_so_line FROM sales_order_lines
            WHERE id = v_do_line.sales_order_line_id;
            IF v_so_line.sales_order_id <> v_do.sales_order_id THEN
              PERFORM fn_raise_error('DO_SO_MISMATCH',
                'Baris surat jalan tidak sesuai dengan sales order induk '
                '(3-way match gagal).');
            END IF;
            v_subtotal := v_subtotal
              + (v_do_line.qty_delivered * v_so_line.unit_price);
            v_total_cogs := v_total_cogs + v_do_line.total_cost;
          END LOOP;

          v_tax_amount := ROUND(v_subtotal * p_tax_rate_pct / 100, 2);
          v_total_amount := v_subtotal + v_tax_amount;
          v_invoice_number := 'INV-' || to_char(CURRENT_DATE, 'YYYYMM') || '-'
            || substr(gen_random_uuid()::text, 1, 6);

          INSERT INTO ar_invoices
            (entity_id, customer_id, delivery_order_id, invoice_number,
             invoice_date, due_date, status, subtotal, tax_amount,
             total_amount)
          VALUES
            (v_so.entity_id, v_so.customer_id, p_delivery_order_id,
             v_invoice_number, CURRENT_DATE,
             CURRENT_DATE + (SELECT payment_term_days FROM customers
                             WHERE id = v_so.customer_id),
             'ISSUED', v_subtotal, v_tax_amount, v_total_amount)
          RETURNING id INTO v_invoice_id;

          INSERT INTO ar_invoice_lines
            (ar_invoice_id, item_id, qty, unit_price, line_total)
          SELECT v_invoice_id, dol.item_id, dol.qty_delivered,
                 sol.unit_price, dol.qty_delivered * sol.unit_price
          FROM delivery_order_lines dol
          JOIN sales_order_lines sol
            ON sol.id = dol.sales_order_line_id
          WHERE dol.delivery_order_id = p_delivery_order_id;

          -- GL: Dr AR / Cr Revenue / Cr PPN Keluaran,
          --     plus Dr COGS / Cr Inventory per item.
          v_je_lines := jsonb_build_array(
            jsonb_build_object('account_id',
              (SELECT gl_ar_account_id FROM entity_gl_defaults
               WHERE entity_id = v_so.entity_id),
              'debit_amount', v_total_amount, 'credit_amount', 0),
            jsonb_build_object('account_id',
              (SELECT gl_sales_revenue_account_id FROM entity_gl_defaults
               WHERE entity_id = v_so.entity_id),
              'debit_amount', 0, 'credit_amount', v_subtotal),
            jsonb_build_object('account_id',
              (SELECT gl_ppn_keluaran_account_id FROM entity_gl_defaults
               WHERE entity_id = v_so.entity_id),
              'debit_amount', 0, 'credit_amount', v_tax_amount)
          );

          FOR v_cogs_line IN
            SELECT i.gl_cogs_account_id, i.gl_inventory_account_id,
                   dol.total_cost
            FROM delivery_order_lines dol
            JOIN items i ON i.id = dol.item_id
            WHERE dol.delivery_order_id = p_delivery_order_id
              AND dol.total_cost > 0
          LOOP
            IF v_cogs_line.gl_cogs_account_id IS NULL
               OR v_cogs_line.gl_inventory_account_id IS NULL THEN
              PERFORM fn_raise_error('ITEM_COGS_ACCOUNT_MISSING',
                'Item pada surat jalan ini belum punya '
                'gl_cogs_account_id/gl_inventory_account_id.');
            END IF;
            v_je_lines := v_je_lines
              || jsonb_build_object('account_id',
                  v_cogs_line.gl_cogs_account_id,
                  'debit_amount', v_cogs_line.total_cost,
                  'credit_amount', 0)
              || jsonb_build_object('account_id',
                  v_cogs_line.gl_inventory_account_id,
                  'debit_amount', 0,
                  'credit_amount', v_cogs_line.total_cost);
          END LOOP;

          v_je_result := fn_create_journal_entry(
            v_so.entity_id, CURRENT_DATE,
            format('Sales Invoice %s', v_invoice_number), 'IDR', v_je_lines);
          PERFORM fn_post_journal_entry(
            (v_je_result->>'journal_entry_id')::uuid);

          UPDATE ar_invoices
          SET journal_entry_id = (v_je_result->>'journal_entry_id')::uuid
          WHERE id = v_invoice_id;
          UPDATE delivery_orders SET status = 'INVOICED'
          WHERE id = p_delivery_order_id;

          RETURN jsonb_build_object('success', TRUE,
            'invoice_id', v_invoice_id,
            'invoice_number', v_invoice_number,
            'total_amount', v_total_amount,
            'cogs', v_total_cogs);
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC: fn_record_ar_payment
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_record_ar_payment(
          p_customer_id UUID, p_amount NUMERIC, p_payment_date DATE,
          p_payment_method VARCHAR, p_allocations JSONB DEFAULT NULL
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_entity_id     UUID;
          v_payment_id    UUID;
          v_remaining     NUMERIC(18,2) := p_amount;
          v_invoice       RECORD;
          v_alloc         JSONB;
          v_take          NUMERIC(18,2);
          v_je_result     JSONB;
        BEGIN
          IF fn_current_role() NOT IN
             ('FINANCE_OPERATOR','DEPT_HEAD_FA','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only finance roles can record AR payments.');
          END IF;

          SELECT entity_id INTO v_entity_id FROM customers
          WHERE id = p_customer_id;
          IF v_entity_id IS NULL THEN
            PERFORM fn_raise_error('CUSTOMER_NOT_FOUND',
              'Customer tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_entity_id THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only record payments for your own customers.');
          END IF;
          IF p_amount <= 0 THEN
            PERFORM fn_raise_error('INVALID_AMOUNT',
              'Jumlah pembayaran harus lebih dari 0.');
          END IF;

          INSERT INTO ar_payments
            (entity_id, customer_id, payment_date, amount,
             payment_method, created_by)
          VALUES
            (v_entity_id, p_customer_id, p_payment_date, p_amount,
             p_payment_method, fn_current_user_id())
          RETURNING id INTO v_payment_id;

          IF p_allocations IS NOT NULL THEN
            FOR v_alloc IN SELECT * FROM jsonb_array_elements(p_allocations)
            LOOP
              INSERT INTO ar_payment_allocations
                (ar_payment_id, ar_invoice_id, allocated_amount)
              VALUES
                (v_payment_id, (v_alloc->>'invoice_id')::uuid,
                 (v_alloc->>'amount')::numeric);
              UPDATE ar_invoices
              SET paid_amount = paid_amount
                  + (v_alloc->>'amount')::numeric,
                  status = (CASE
                    WHEN paid_amount + (v_alloc->>'amount')::numeric
                         >= total_amount THEN 'PAID'
                    ELSE 'PARTIALLY_PAID' END)::ar_invoice_status_enum
              WHERE id = (v_alloc->>'invoice_id')::uuid;
            END LOOP;
          ELSE
            -- Auto-allocate FIFO by due date.
            FOR v_invoice IN
              SELECT * FROM ar_invoices
              WHERE customer_id = p_customer_id
                AND status IN ('ISSUED','PARTIALLY_PAID')
              ORDER BY due_date ASC
              FOR UPDATE
            LOOP
              EXIT WHEN v_remaining <= 0;
              v_take := LEAST(v_invoice.total_amount
                - v_invoice.paid_amount, v_remaining);
              INSERT INTO ar_payment_allocations
                (ar_payment_id, ar_invoice_id, allocated_amount)
              VALUES (v_payment_id, v_invoice.id, v_take);
              UPDATE ar_invoices
              SET paid_amount = paid_amount + v_take,
                  status = (CASE
                    WHEN paid_amount + v_take >= total_amount
                    THEN 'PAID' ELSE 'PARTIALLY_PAID'
                  END)::ar_invoice_status_enum
              WHERE id = v_invoice.id;
              v_remaining := v_remaining - v_take;
            END LOOP;
          END IF;

          -- GL: Dr Cash/Bank, Cr AR.
          v_je_result := fn_create_journal_entry(
            v_entity_id, p_payment_date, 'AR Payment Received', 'IDR',
            jsonb_build_array(
              jsonb_build_object('account_id',
                (SELECT gl_kas_bank_default_account_id
                 FROM entity_gl_defaults WHERE entity_id = v_entity_id),
                'debit_amount', p_amount, 'credit_amount', 0),
              jsonb_build_object('account_id',
                (SELECT gl_ar_account_id FROM entity_gl_defaults
                 WHERE entity_id = v_entity_id),
                'debit_amount', 0, 'credit_amount', p_amount)
            ));
          PERFORM fn_post_journal_entry(
            (v_je_result->>'journal_entry_id')::uuid);
          UPDATE ar_payments
          SET journal_entry_id = (v_je_result->>'journal_entry_id')::uuid
          WHERE id = v_payment_id;

          RETURN jsonb_build_object('success', TRUE,
            'payment_id', v_payment_id, 'amount', p_amount);
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC: fn_process_pos_sale
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_process_pos_sale(
          p_warehouse_id UUID, p_lines JSONB, p_payment_method VARCHAR
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_entity_id     UUID;
          v_line          JSONB;
          v_total         NUMERIC(18,2) := 0;
          v_total_cogs    NUMERIC(18,2) := 0;
          v_issue_result  JSONB;
          v_txn_id        UUID;
          v_txn_number    VARCHAR(30);
        BEGIN
          IF fn_current_role() NOT IN
             ('SALES_OPERATOR','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only sales operators can run POS.');
          END IF;

          SELECT entity_id INTO v_entity_id FROM warehouses
          WHERE id = p_warehouse_id;
          IF v_entity_id IS NULL THEN
            PERFORM fn_raise_error('WAREHOUSE_NOT_FOUND',
              'Gudang tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_entity_id THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'POS sale must stay within your own entity.');
          END IF;

          v_txn_number := 'POS-' || to_char(now(), 'YYYYMMDDHH24MISS')
            || '-' || substr(gen_random_uuid()::text, 1, 4);

          INSERT INTO pos_transactions
            (entity_id, warehouse_id, transaction_number, total_amount,
             payment_method, cashier_id)
          VALUES
            (v_entity_id, p_warehouse_id, v_txn_number, 0,
             p_payment_method, fn_current_user_id())
          RETURNING id INTO v_txn_id;

          FOR v_line IN SELECT * FROM jsonb_array_elements(p_lines) LOOP
            v_issue_result := fn_issue_stock(
              (v_line->>'item_id')::uuid, p_warehouse_id,
              (v_line->>'qty')::numeric, 'POS', v_txn_id);
            v_total_cogs := v_total_cogs
              + (v_issue_result->>'total_cost')::numeric;
            v_total := v_total
              + ((v_line->>'qty')::numeric
                 * (v_line->>'unit_price')::numeric);

            INSERT INTO pos_transaction_lines
              (pos_transaction_id, item_id, qty, unit_price, line_total)
            VALUES
              (v_txn_id, (v_line->>'item_id')::uuid,
               (v_line->>'qty')::numeric,
               (v_line->>'unit_price')::numeric,
               (v_line->>'qty')::numeric
                 * (v_line->>'unit_price')::numeric);
          END LOOP;

          UPDATE pos_transactions SET total_amount = v_total
          WHERE id = v_txn_id;

          -- GL posting is batched per shift/day via
          -- fn_post_pos_batch_journal (fast path, < 100ms target).

          RETURN jsonb_build_object('success', TRUE,
            'pos_transaction_id', v_txn_id,
            'transaction_number', v_txn_number,
            'total_amount', v_total, 'total_cogs', v_total_cogs);
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC: fn_post_pos_batch_journal
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_post_pos_batch_journal(p_entity_id UUID)
        RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_total_sales  NUMERIC(18,2);
          v_total_cogs   NUMERIC(18,2);
          v_txn_count    INT;
          v_je_lines     JSONB;
          v_je_result    JSONB;
          v_je_id        UUID;
        BEGIN
          SELECT COUNT(*), COALESCE(SUM(total_amount), 0)
          INTO v_txn_count, v_total_sales
          FROM pos_transactions
          WHERE entity_id = p_entity_id AND journal_entry_id IS NULL;

          IF v_txn_count = 0 THEN
            RETURN jsonb_build_object('success', TRUE, 'txn_count', 0,
              'note', 'Tidak ada transaksi POS baru untuk diposting.');
          END IF;

          SELECT COALESCE(SUM(st.total_cost), 0) INTO v_total_cogs
          FROM stock_transactions st
          WHERE st.reference_type = 'POS'
            AND st.reference_id IN (SELECT id FROM pos_transactions
              WHERE entity_id = p_entity_id
                AND journal_entry_id IS NULL);

          v_je_lines := jsonb_build_array(
            jsonb_build_object('account_id',
              (SELECT gl_kas_bank_default_account_id
               FROM entity_gl_defaults WHERE entity_id = p_entity_id),
              'debit_amount', v_total_sales, 'credit_amount', 0),
            jsonb_build_object('account_id',
              (SELECT gl_sales_revenue_account_id
               FROM entity_gl_defaults WHERE entity_id = p_entity_id),
              'debit_amount', 0, 'credit_amount', v_total_sales)
          );
          IF v_total_cogs > 0 THEN
            v_je_lines := v_je_lines
              || jsonb_build_object('account_id',
                  (SELECT i.gl_cogs_account_id FROM items i
                    JOIN pos_transaction_lines ptl ON ptl.item_id = i.id
                    JOIN pos_transactions pt ON pt.id = ptl.pos_transaction_id
                   WHERE pt.entity_id = p_entity_id
                     AND pt.journal_entry_id IS NULL
                   LIMIT 1),
                  'debit_amount', v_total_cogs, 'credit_amount', 0)
              || jsonb_build_object('account_id',
                  (SELECT i.gl_inventory_account_id FROM items i
                    JOIN pos_transaction_lines ptl ON ptl.item_id = i.id
                    JOIN pos_transactions pt ON pt.id = ptl.pos_transaction_id
                   WHERE pt.entity_id = p_entity_id
                     AND pt.journal_entry_id IS NULL
                   LIMIT 1),
                  'debit_amount', 0, 'credit_amount', v_total_cogs);
          END IF;

          v_je_result := fn_create_journal_entry(
            p_entity_id, CURRENT_DATE,
            format('POS Batch Posting (%s transaksi)', v_txn_count),
            'IDR', v_je_lines);
          v_je_id := (v_je_result->>'journal_entry_id')::uuid;
          PERFORM fn_post_journal_entry(v_je_id);

          UPDATE pos_transactions SET journal_entry_id = v_je_id
          WHERE entity_id = p_entity_id AND journal_entry_id IS NULL;

          RETURN jsonb_build_object('success', TRUE,
            'txn_count', v_txn_count, 'total_sales', v_total_sales,
            'total_cogs', v_total_cogs, 'journal_entry_id', v_je_id);
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS fn_post_pos_batch_journal(UUID)")
    op.execute("DROP FUNCTION IF EXISTS fn_process_pos_sale(UUID, JSONB, VARCHAR)")
    op.execute("DROP FUNCTION IF EXISTS fn_record_ar_payment(UUID, NUMERIC, DATE, VARCHAR, JSONB)")
    op.execute("DROP FUNCTION IF EXISTS fn_issue_ar_invoice(UUID, NUMERIC)")
    op.execute("DROP FUNCTION IF EXISTS fn_create_delivery_order(UUID, DATE, JSONB)")
    op.execute("DROP FUNCTION IF EXISTS fn_confirm_sales_order(UUID)")
    op.execute("DROP FUNCTION IF EXISTS fn_check_credit_limit(UUID, NUMERIC)")
    op.execute("DROP TABLE IF EXISTS pos_transaction_lines CASCADE")
    op.execute("DROP TABLE IF EXISTS pos_transactions CASCADE")
    op.execute("DROP TABLE IF EXISTS ar_payment_allocations CASCADE")
    op.execute("DROP TABLE IF EXISTS ar_payments CASCADE")
    op.execute("DROP TABLE IF EXISTS ar_invoice_lines CASCADE")
    op.execute("DROP TABLE IF EXISTS ar_invoices CASCADE")
    op.execute("DROP TABLE IF EXISTS delivery_order_lines CASCADE")
    op.execute("DROP TABLE IF EXISTS delivery_orders CASCADE")
    op.execute("DROP TABLE IF EXISTS sales_order_lines CASCADE")
    op.execute("DROP TABLE IF EXISTS sales_orders CASCADE")
    op.execute("DROP TABLE IF EXISTS customers CASCADE")
    op.execute("DROP TABLE IF EXISTS entity_gl_defaults CASCADE")
    op.execute("DROP TYPE IF EXISTS ar_invoice_status_enum")
    op.execute("DROP TYPE IF EXISTS do_status_enum")
    op.execute("DROP TYPE IF EXISTS so_status_enum")
