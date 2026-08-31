"""Add Modul 5: Procurement & AP (PUTG) + Dynamic Approval Engine slice

Revision ID: e8b1d4f73a29
Revises: d7c3f5a82b16
Create Date: 2026-08-31

Tables (13): vendors, purchase_requests + lines, purchase_orders +
lines, goods_received_notes + grn_lines, ap_bills + lines,
ap_payments + allocations, approval_thresholds (Modul 6 slice —
MUST deploy together with Modul 5 per PRD note).

Enums (5): pr_status, po_status, grn_status, inspection_status,
ap_bill_status (+ approval_doc_type_enum).

entity_gl_defaults: + gl_ap_account_id, gl_ppn_masukan_account_id,
gl_grir_clearing_account_id, gl_price_variance_account_id.

RPCs (8):
- fn_get_required_approval_role (Dynamic Approval Engine, STABLE)
- fn_submit_purchase_order (DRAFT -> PENDING_APPROVAL + threshold)
- fn_approve_purchase_order (role >= required_approval_role)
- fn_receive_goods (PO APPROVED -> GRN DRAFT, stock NOT moved yet)
- fn_inspect_grn (PUTG: accepted -> fn_receive_stock + GL
  Dr Inventory / Cr GR/IR @ PO price; rejected never enters stock)
- fn_create_ap_bill (GRN PASSED/PARTIAL only, one bill per GRN)
- fn_match_and_approve_ap_bill (3-way match Bill/PO/GRN, tolerance
  2% default, DISPUTED on mismatch, GL clears GR/IR + PPN Masukan
  + AP + Price Variance)
- fn_record_ap_payment (Dr AP / Cr Kas-Bank, auto-allocate FIFO)

Adaptasi dialek (aturan repo): auth.uid() -> fn_current_user_id(),
auth.users -> user_profiles; role/entity guards moved INTO RPCs;
`SET status = CASE ...` gets explicit ::enum casts.

Migration ini ditulis dalam 3 tahap append (limit write_file ~40KB).
"""

from alembic import op

revision = "e8b1d4f73a29"
down_revision = "d7c3f5a82b16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enums
    # ------------------------------------------------------------------
    op.execute(
        "CREATE TYPE pr_status_enum AS ENUM "
        "('DRAFT','APPROVED','REJECTED','CONVERTED')"
    )
    op.execute(
        "CREATE TYPE po_status_enum AS ENUM "
        "('DRAFT','PENDING_APPROVAL','APPROVED','PARTIALLY_RECEIVED',"
        "'RECEIVED','CANCELLED')"
    )
    op.execute("CREATE TYPE grn_status_enum AS ENUM ('DRAFT','COMPLETED')")
    op.execute(
        "CREATE TYPE inspection_status_enum AS ENUM "
        "('PENDING','PASSED','PARTIAL','REJECTED')"
    )
    op.execute(
        "CREATE TYPE ap_bill_status_enum AS ENUM "
        "('DRAFT','MATCHED','APPROVED','PAID','DISPUTED')"
    )
    op.execute(
        "CREATE TYPE approval_doc_type_enum AS ENUM ('KASBON','PO')"
    )
    # Section 5 requires Direksi authorization for PO/Kasbon > 5jt;
    # role_enum needs the value (Modul 6 note, deployed with M5).
    op.execute(
        "ALTER TYPE role_enum ADD VALUE IF NOT EXISTS 'DIREKSI'"
    )

    # ------------------------------------------------------------------
    # entity_gl_defaults additions
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE entity_gl_defaults
          ADD COLUMN IF NOT EXISTS gl_ap_account_id UUID
            REFERENCES chart_of_accounts(id),
          ADD COLUMN IF NOT EXISTS gl_ppn_masukan_account_id UUID
            REFERENCES chart_of_accounts(id),
          ADD COLUMN IF NOT EXISTS gl_grir_clearing_account_id UUID
            REFERENCES chart_of_accounts(id),
          ADD COLUMN IF NOT EXISTS gl_price_variance_account_id UUID
            REFERENCES chart_of_accounts(id)
        """
    )

    # ------------------------------------------------------------------
    # Vendors
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE vendors (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          vendor_code VARCHAR(20) NOT NULL,
          vendor_name VARCHAR(150) NOT NULL,
          payment_term_days SMALLINT NOT NULL DEFAULT 30,
          npwp VARCHAR(20),
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          UNIQUE (entity_id, vendor_code)
        )
        """
    )

    # ------------------------------------------------------------------
    # Purchase requests (PR)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE purchase_requests (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          department_code VARCHAR(30),
          pr_number VARCHAR(30) NOT NULL,
          request_date DATE NOT NULL,
          status pr_status_enum NOT NULL DEFAULT 'DRAFT',
          requested_by UUID NOT NULL REFERENCES user_profiles(id),
          approved_by UUID REFERENCES user_profiles(id),
          UNIQUE (entity_id, pr_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE purchase_request_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          pr_id UUID NOT NULL REFERENCES purchase_requests(id)
            ON DELETE CASCADE,
          item_id UUID NOT NULL REFERENCES items(id),
          qty_requested NUMERIC(18,4) NOT NULL
            CHECK (qty_requested > 0),
          estimated_unit_price NUMERIC(18,2) NOT NULL DEFAULT 0
        )
        """
    )

    # ------------------------------------------------------------------
    # Purchase orders (PO)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE purchase_orders (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          vendor_id UUID NOT NULL REFERENCES vendors(id),
          warehouse_id UUID NOT NULL REFERENCES warehouses(id),
          pr_id UUID REFERENCES purchase_requests(id),
          po_number VARCHAR(30) NOT NULL,
          order_date DATE NOT NULL,
          status po_status_enum NOT NULL DEFAULT 'DRAFT',
          required_approval_role role_enum,
          total_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
          created_by UUID NOT NULL REFERENCES user_profiles(id),
          approved_by UUID REFERENCES user_profiles(id),
          approved_at TIMESTAMPTZ,
          UNIQUE (entity_id, po_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE purchase_order_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          purchase_order_id UUID NOT NULL REFERENCES purchase_orders(id)
            ON DELETE CASCADE,
          item_id UUID NOT NULL REFERENCES items(id),
          qty_ordered NUMERIC(18,4) NOT NULL CHECK (qty_ordered > 0),
          qty_received NUMERIC(18,4) NOT NULL DEFAULT 0,
          unit_price NUMERIC(18,2) NOT NULL CHECK (unit_price >= 0),
          line_total NUMERIC(18,2) NOT NULL,
          CONSTRAINT chk_received_not_exceed
            CHECK (qty_received <= qty_ordered)
        )
        """
    )

    # ------------------------------------------------------------------
    # GRN (BPB) — physical receipt; stock waits for inspection
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE goods_received_notes (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          purchase_order_id UUID NOT NULL REFERENCES purchase_orders(id),
          warehouse_id UUID NOT NULL REFERENCES warehouses(id),
          grn_number VARCHAR(30) NOT NULL,
          received_date DATE NOT NULL,
          status grn_status_enum NOT NULL DEFAULT 'DRAFT',
          inspection_status inspection_status_enum NOT NULL
            DEFAULT 'PENDING',
          inspected_by UUID REFERENCES user_profiles(id),
          inspected_at TIMESTAMPTZ,
          created_by UUID NOT NULL REFERENCES user_profiles(id),
          UNIQUE (entity_id, grn_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE grn_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          grn_id UUID NOT NULL REFERENCES goods_received_notes(id)
            ON DELETE CASCADE,
          purchase_order_line_id UUID NOT NULL
            REFERENCES purchase_order_lines(id),
          item_id UUID NOT NULL REFERENCES items(id),
          qty_received NUMERIC(18,4) NOT NULL CHECK (qty_received > 0),
          qty_accepted NUMERIC(18,4) NOT NULL DEFAULT 0,
          qty_rejected NUMERIC(18,4) NOT NULL DEFAULT 0,
          CONSTRAINT chk_accept_reject_sum
            CHECK (qty_accepted + qty_rejected <= qty_received)
        )
        """
    )

    # ------------------------------------------------------------------
    # AP bills + payments
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE ap_bills (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          vendor_id UUID NOT NULL REFERENCES vendors(id),
          grn_id UUID NOT NULL REFERENCES goods_received_notes(id),
          bill_number VARCHAR(30) NOT NULL,
          bill_date DATE NOT NULL,
          due_date DATE NOT NULL,
          status ap_bill_status_enum NOT NULL DEFAULT 'DRAFT',
          subtotal NUMERIC(18,2) NOT NULL DEFAULT 0,
          tax_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
          total_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
          paid_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
          dispute_reason TEXT,
          journal_entry_id UUID REFERENCES journal_entries(id),
          UNIQUE (entity_id, bill_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ap_bill_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          ap_bill_id UUID NOT NULL REFERENCES ap_bills(id)
            ON DELETE CASCADE,
          item_id UUID NOT NULL REFERENCES items(id),
          qty NUMERIC(18,4) NOT NULL,
          unit_price NUMERIC(18,2) NOT NULL,
          line_total NUMERIC(18,2) NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ap_payments (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          vendor_id UUID NOT NULL REFERENCES vendors(id),
          payment_date DATE NOT NULL,
          amount NUMERIC(18,2) NOT NULL CHECK (amount > 0),
          payment_method VARCHAR(20) NOT NULL,
          journal_entry_id UUID REFERENCES journal_entries(id),
          created_by UUID NOT NULL REFERENCES user_profiles(id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ap_payment_allocations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          ap_payment_id UUID NOT NULL REFERENCES ap_payments(id)
            ON DELETE CASCADE,
          ap_bill_id UUID NOT NULL REFERENCES ap_bills(id),
          allocated_amount NUMERIC(18,2) NOT NULL
            CHECK (allocated_amount > 0)
        )
        """
    )

    # ------------------------------------------------------------------
    # Dynamic Approval Engine (Modul 6 slice, wajib bareng Modul 5)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE approval_thresholds (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          document_type approval_doc_type_enum NOT NULL,
          min_amount NUMERIC(18,2) NOT NULL,
          required_role role_enum NOT NULL,
          notify_channels VARCHAR(20)[] NOT NULL
            DEFAULT ARRAY['EMAIL'],
          UNIQUE (entity_id, document_type, min_amount)
        )
        """
    )

    # ------------------------------------------------------------------
    # RLS + revoke
    # ------------------------------------------------------------------
    for tbl in (
        "vendors",
        "purchase_requests",
        "purchase_orders",
        "goods_received_notes",
        "ap_bills",
        "ap_payments",
        "approval_thresholds",
    ):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY vendor_entity_policy ON vendors FOR ALL USING (
          entity_id = fn_current_entity_id()
        )
        """
    )
    op.execute(
        """
        CREATE POLICY pr_entity_policy ON purchase_requests FOR ALL
        USING (entity_id = fn_current_entity_id())
        """
    )
    op.execute(
        """
        CREATE POLICY po_entity_policy ON purchase_orders FOR ALL
        USING (entity_id = fn_current_entity_id())
        """
    )
    op.execute(
        """
        CREATE POLICY grn_entity_policy ON goods_received_notes FOR ALL
        USING (entity_id = fn_current_entity_id())
        """
    )
    op.execute(
        """
        CREATE POLICY ap_bill_entity_policy ON ap_bills FOR ALL USING (
          entity_id = fn_current_entity_id()
        )
        """
    )
    op.execute(
        """
        CREATE POLICY ap_payment_entity_policy ON ap_payments FOR ALL
        USING (entity_id = fn_current_entity_id())
        """
    )
    op.execute(
        """
        CREATE POLICY approval_threshold_entity_policy
        ON approval_thresholds FOR ALL USING (
          entity_id = fn_current_entity_id()
        )
        """
    )
    op.execute(
        "REVOKE UPDATE, DELETE ON goods_received_notes, ap_bills "
        "FROM PUBLIC"
    )


    # ------------------------------------------------------------------
    # RPC 1: fn_get_required_approval_role (Dynamic Approval Engine)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_get_required_approval_role(
          p_entity_id UUID,
          p_document_type approval_doc_type_enum,
          p_amount NUMERIC
        ) RETURNS role_enum LANGUAGE plpgsql STABLE AS $$
        DECLARE
          v_role role_enum;
        BEGIN
          SELECT required_role INTO v_role FROM approval_thresholds
            WHERE entity_id = p_entity_id
              AND document_type = p_document_type
              AND min_amount <= p_amount
            ORDER BY min_amount DESC LIMIT 1;
          RETURN COALESCE(v_role, 'DEPT_HEAD_FA');
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 2: fn_submit_purchase_order
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_submit_purchase_order(
          p_purchase_order_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_po             purchase_orders%ROWTYPE;
          v_line_total     NUMERIC(18,2);
          v_required_role  role_enum;
        BEGIN
          IF fn_current_role() NOT IN
             ('WAREHOUSE_OPERATOR','DEPT_HEAD_WAREHOUSE',
              'FINANCE_OPERATOR','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only warehouse/finance staff can submit POs.');
          END IF;

          SELECT * INTO v_po FROM purchase_orders
          WHERE id = p_purchase_order_id FOR UPDATE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('PO_NOT_FOUND',
              'Purchase order tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_po.entity_id
          THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only submit POs of your own entity.');
          END IF;
          IF v_po.status <> 'DRAFT' THEN
            PERFORM fn_raise_error('PO_INVALID_STATUS',
              format('PO berstatus %s, tidak bisa disubmit.',
                     v_po.status));
          END IF;

          SELECT COALESCE(SUM(line_total), 0) INTO v_line_total
          FROM purchase_order_lines
          WHERE purchase_order_id = p_purchase_order_id;
          IF v_line_total = 0 THEN
            PERFORM fn_raise_error('PO_EMPTY',
              'PO tidak memiliki baris item.');
          END IF;

          v_required_role := fn_get_required_approval_role(
            v_po.entity_id, 'PO', v_line_total);

          UPDATE purchase_orders SET
            status = 'PENDING_APPROVAL',
            total_amount = v_line_total,
            required_approval_role = v_required_role
          WHERE id = p_purchase_order_id;

          RETURN jsonb_build_object('success', TRUE,
            'purchase_order_id', p_purchase_order_id,
            'required_approval_role', v_required_role,
            'total_amount', v_line_total);
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 3: fn_approve_purchase_order
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_approve_purchase_order(
          p_purchase_order_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_po purchase_orders%ROWTYPE;
        BEGIN
          SELECT * INTO v_po FROM purchase_orders
          WHERE id = p_purchase_order_id FOR UPDATE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('PO_NOT_FOUND',
              'Purchase order tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_po.entity_id
          THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only approve POs of your own entity.');
          END IF;
          IF v_po.status <> 'PENDING_APPROVAL' THEN
            PERFORM fn_raise_error('PO_INVALID_STATUS',
              format('PO berstatus %s, tidak bisa diapprove.',
                     v_po.status));
          END IF;
          IF fn_current_role() NOT IN
             (v_po.required_approval_role, 'SUPER_ADMIN') THEN
            PERFORM fn_raise_error('INSUFFICIENT_APPROVAL_AUTHORITY',
              format('PO sebesar %s memerlukan otorisasi %s.',
                     v_po.total_amount, v_po.required_approval_role));
          END IF;

          UPDATE purchase_orders SET
            status = 'APPROVED',
            approved_by = fn_current_user_id(),
            approved_at = now()
          WHERE id = p_purchase_order_id;

          INSERT INTO system_logs
            (actor_id, entity_id, action, table_name, record_id,
             after_data)
          VALUES (fn_current_user_id(), v_po.entity_id, 'APPROVE',
            'purchase_orders', p_purchase_order_id::text,
            jsonb_build_object('status', 'APPROVED',
              'approver_role', fn_current_role()));

          RETURN jsonb_build_object('success', TRUE,
            'purchase_order_id', p_purchase_order_id,
            'status', 'APPROVED');
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 4: fn_receive_goods — physical receipt, stock NOT moved yet
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_receive_goods(
          p_purchase_order_id UUID,
          p_received_date DATE,
          p_lines JSONB
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_po        purchase_orders%ROWTYPE;
          v_grn_id    UUID;
          v_grn_number VARCHAR(30);
          v_line      JSONB;
          v_po_line   purchase_order_lines%ROWTYPE;
        BEGIN
          IF fn_current_role() NOT IN
             ('WAREHOUSE_OPERATOR','DEPT_HEAD_WAREHOUSE','SUPER_ADMIN')
          THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only warehouse staff can receive goods.');
          END IF;

          SELECT * INTO v_po FROM purchase_orders
          WHERE id = p_purchase_order_id FOR UPDATE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('PO_NOT_FOUND',
              'Purchase order tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_po.entity_id
          THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only receive goods for your own entity.');
          END IF;
          IF v_po.status NOT IN ('APPROVED','PARTIALLY_RECEIVED') THEN
            PERFORM fn_raise_error('PO_INVALID_STATUS',
              format('Purchase order berstatus %s, tidak bisa '
                     'menerima barang.', v_po.status));
          END IF;

          v_grn_number := 'GRN-' || to_char(p_received_date, 'YYYYMMDD')
            || '-' || substr(gen_random_uuid()::text, 1, 6);
          INSERT INTO goods_received_notes
            (entity_id, purchase_order_id, warehouse_id, grn_number,
             received_date, status, created_by)
          VALUES (v_po.entity_id, p_purchase_order_id,
            v_po.warehouse_id, v_grn_number, p_received_date,
            'DRAFT', fn_current_user_id())
          RETURNING id INTO v_grn_id;

          FOR v_line IN SELECT * FROM jsonb_array_elements(p_lines)
          LOOP
            SELECT * INTO v_po_line FROM purchase_order_lines
            WHERE id = (v_line->>'purchase_order_line_id')::uuid;
            IF v_po_line.qty_received
               + (v_line->>'qty_received')::numeric
               > v_po_line.qty_ordered THEN
              PERFORM fn_raise_error('RECEIPT_EXCEEDS_ORDER',
                format('Qty diterima melebihi sisa qty PO untuk '
                       'item %s.', v_po_line.item_id));
            END IF;
            INSERT INTO grn_lines
              (grn_id, purchase_order_line_id, item_id, qty_received)
            VALUES (v_grn_id, v_po_line.id, v_po_line.item_id,
              (v_line->>'qty_received')::numeric);
          END LOOP;

          RETURN jsonb_build_object('success', TRUE,
            'grn_id', v_grn_id, 'grn_number', v_grn_number,
            'inspection_status', 'PENDING');
        END;
        $$;
        """
    )


    # ------------------------------------------------------------------
    # RPC 5: fn_inspect_grn — PUTG; accepted qty enters stock + GL
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_inspect_grn(
          p_grn_id UUID, p_line_results JSONB
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_grn          goods_received_notes%ROWTYPE;
          v_po           purchase_orders%ROWTYPE;
          v_line         JSONB;
          v_grn_line     grn_lines%ROWTYPE;
          v_po_line      purchase_order_lines%ROWTYPE;
          v_total_accepted_value NUMERIC(18,2) := 0;
          v_any_rejected BOOLEAN := FALSE;
          v_all_accepted BOOLEAN := TRUE;
          v_je_result    JSONB;
          v_po_all_received BOOLEAN;
        BEGIN
          IF fn_current_role() NOT IN
             ('WAREHOUSE_OPERATOR','DEPT_HEAD_WAREHOUSE','SUPER_ADMIN')
          THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only warehouse staff can inspect GRNs.');
          END IF;

          SELECT * INTO v_grn FROM goods_received_notes
          WHERE id = p_grn_id FOR UPDATE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('GRN_NOT_FOUND',
              'GRN tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_grn.entity_id
          THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only inspect GRNs of your own entity.');
          END IF;
          IF v_grn.status <> 'DRAFT' THEN
            PERFORM fn_raise_error('GRN_ALREADY_INSPECTED',
              'GRN ini sudah pernah diinspeksi.');
          END IF;
          SELECT * INTO v_po FROM purchase_orders
          WHERE id = v_grn.purchase_order_id;

          FOR v_line IN
            SELECT * FROM jsonb_array_elements(p_line_results)
          LOOP
            SELECT * INTO v_grn_line FROM grn_lines
            WHERE id = (v_line->>'grn_line_id')::uuid FOR UPDATE;
            SELECT * INTO v_po_line FROM purchase_order_lines
            WHERE id = v_grn_line.purchase_order_line_id;

            IF (v_line->>'qty_accepted')::numeric
               + (v_line->>'qty_rejected')::numeric
               > v_grn_line.qty_received THEN
              PERFORM fn_raise_error('INSPECTION_QTY_MISMATCH',
                'Total accepted + rejected melebihi qty yang '
                'diterima fisik.');
            END IF;

            UPDATE grn_lines SET
              qty_accepted = (v_line->>'qty_accepted')::numeric,
              qty_rejected = (v_line->>'qty_rejected')::numeric
            WHERE id = v_grn_line.id;

            IF (v_line->>'qty_rejected')::numeric > 0 THEN
              v_any_rejected := TRUE;
            END IF;
            IF (v_line->>'qty_accepted')::numeric
               < v_grn_line.qty_received THEN
              v_all_accepted := FALSE;
            END IF;

            IF (v_line->>'qty_accepted')::numeric > 0 THEN
              PERFORM fn_receive_stock(
                v_grn_line.item_id, v_grn.warehouse_id,
                (v_line->>'qty_accepted')::numeric,
                v_po_line.unit_price, 'GRN', p_grn_id, NULL);
              v_total_accepted_value :=
                v_total_accepted_value
                + ROUND((v_line->>'qty_accepted')::numeric
                        * v_po_line.unit_price, 2);
              UPDATE purchase_order_lines
              SET qty_received = qty_received
                  + (v_line->>'qty_accepted')::numeric
              WHERE id = v_po_line.id;
            END IF;
          END LOOP;

          IF v_total_accepted_value > 0 THEN
            v_je_result := fn_create_journal_entry(
              v_grn.entity_id, v_grn.received_date,
              format('GRN Inspection %s — Inventory Receipt',
                     v_grn.grn_number),
              'IDR',
              jsonb_build_array(
                jsonb_build_object('account_id',
                  (SELECT i.gl_inventory_account_id
                   FROM items i JOIN grn_lines gl
                     ON gl.item_id = i.id
                   WHERE gl.grn_id = p_grn_id LIMIT 1),
                  'debit_amount', v_total_accepted_value,
                  'credit_amount', 0),
                jsonb_build_object('account_id',
                  (SELECT gl_grir_clearing_account_id
                   FROM entity_gl_defaults
                   WHERE entity_id = v_grn.entity_id),
                  'debit_amount', 0,
                  'credit_amount', v_total_accepted_value)
              ));
            PERFORM fn_post_journal_entry(
              (v_je_result->>'journal_entry_id')::uuid);
          END IF;

          UPDATE goods_received_notes SET
            status = 'COMPLETED',
            inspection_status = (CASE
              WHEN NOT v_any_rejected THEN 'PASSED'
              WHEN v_total_accepted_value = 0 THEN 'REJECTED'
              ELSE 'PARTIAL'
            END)::inspection_status_enum,
            inspected_by = fn_current_user_id(),
            inspected_at = now()
          WHERE id = p_grn_id;

          SELECT bool_and(qty_received = qty_ordered)
          INTO v_po_all_received
          FROM purchase_order_lines
          WHERE purchase_order_id = v_grn.purchase_order_id;
          UPDATE purchase_orders SET
            status = (CASE WHEN v_po_all_received
                      THEN 'RECEIVED' ELSE 'PARTIALLY_RECEIVED'
                     END)::po_status_enum
          WHERE id = v_grn.purchase_order_id;

          RETURN jsonb_build_object('success', TRUE,
            'grn_id', p_grn_id,
            'total_accepted_value', v_total_accepted_value,
            'any_rejected', v_any_rejected);
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 6: fn_create_ap_bill
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_create_ap_bill(
          p_grn_id UUID,
          p_bill_number VARCHAR,
          p_bill_date DATE,
          p_lines JSONB,
          p_tax_rate_pct NUMERIC DEFAULT 11
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_grn        goods_received_notes%ROWTYPE;
          v_po         purchase_orders%ROWTYPE;
          v_line       JSONB;
          v_subtotal   NUMERIC(18,2) := 0;
          v_tax_amount NUMERIC(18,2);
          v_bill_id    UUID;
        BEGIN
          IF fn_current_role() NOT IN
             ('FINANCE_OPERATOR','DEPT_HEAD_FA','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only finance staff can create AP bills.');
          END IF;

          SELECT * INTO v_grn FROM goods_received_notes
          WHERE id = p_grn_id;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('GRN_NOT_FOUND',
              'GRN tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_grn.entity_id
          THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only create bills for your own entity.');
          END IF;
          IF v_grn.inspection_status NOT IN ('PASSED','PARTIAL')
          THEN
            PERFORM fn_raise_error('GRN_NOT_INSPECTED',
              'Bill hanya dapat dibuat dari GRN yang sudah lolos '
              'inspeksi (PASSED/PARTIAL).');
          END IF;
          IF EXISTS (SELECT 1 FROM ap_bills WHERE grn_id = p_grn_id)
          THEN
            PERFORM fn_raise_error('GRN_ALREADY_BILLED',
              'GRN ini sudah pernah dibuatkan bill sebelumnya.');
          END IF;
          SELECT * INTO v_po FROM purchase_orders
          WHERE id = v_grn.purchase_order_id;

          FOR v_line IN SELECT * FROM jsonb_array_elements(p_lines)
          LOOP
            v_subtotal := v_subtotal
              + ((v_line->>'qty')::numeric
                 * (v_line->>'unit_price')::numeric);
          END LOOP;
          v_tax_amount := ROUND(v_subtotal * p_tax_rate_pct / 100, 2);

          INSERT INTO ap_bills
            (entity_id, vendor_id, grn_id, bill_number, bill_date,
             due_date, status, subtotal, tax_amount, total_amount)
          VALUES (v_grn.entity_id, v_po.vendor_id, p_grn_id,
            p_bill_number, p_bill_date,
            p_bill_date + (SELECT payment_term_days FROM vendors
                           WHERE id = v_po.vendor_id),
            'DRAFT', v_subtotal, v_tax_amount,
            v_subtotal + v_tax_amount)
          RETURNING id INTO v_bill_id;

          INSERT INTO ap_bill_lines
            (ap_bill_id, item_id, qty, unit_price, line_total)
          SELECT v_bill_id,
            (vl->>'item_id')::uuid,
            (vl->>'qty')::numeric,
            (vl->>'unit_price')::numeric,
            ROUND((vl->>'qty')::numeric
                  * (vl->>'unit_price')::numeric, 2)
          FROM jsonb_array_elements(p_lines) vl;

          RETURN jsonb_build_object('success', TRUE,
            'ap_bill_id', v_bill_id,
            'total_amount', v_subtotal + v_tax_amount);
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 7: fn_match_and_approve_ap_bill — automated 3-way matching
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_match_and_approve_ap_bill(
          p_ap_bill_id UUID,
          p_tolerance_pct NUMERIC DEFAULT 2
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_bill           ap_bills%ROWTYPE;
          v_bill_line      RECORD;
          v_grn_line       RECORD;
          v_po_line        purchase_order_lines%ROWTYPE;
          v_variance_pct   NUMERIC;
          v_total_variance NUMERIC(18,2) := 0;
          v_grir_amount    NUMERIC(18,2) := 0;
          v_mismatch_found BOOLEAN := FALSE;
          v_mismatch_detail TEXT := '';
          v_je_lines       JSONB;
          v_je_result      JSONB;
        BEGIN
          IF fn_current_role() NOT IN
             ('FINANCE_OPERATOR','DEPT_HEAD_FA','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only finance staff can match AP bills.');
          END IF;

          SELECT * INTO v_bill FROM ap_bills
          WHERE id = p_ap_bill_id FOR UPDATE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('BILL_NOT_FOUND',
              'AP bill tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_bill.entity_id
          THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only match bills of your own entity.');
          END IF;
          IF v_bill.status <> 'DRAFT' THEN
            PERFORM fn_raise_error('BILL_INVALID_STATUS',
              format('Bill berstatus %s, tidak bisa dilakukan '
                     'matching ulang.', v_bill.status));
          END IF;

          FOR v_bill_line IN
            SELECT * FROM ap_bill_lines
            WHERE ap_bill_id = p_ap_bill_id
          LOOP
            SELECT * INTO v_grn_line FROM grn_lines
            WHERE grn_id = v_bill.grn_id
              AND item_id = v_bill_line.item_id;
            IF NOT FOUND THEN
              v_mismatch_found := TRUE;
              v_mismatch_detail := v_mismatch_detail || format(
                'Item %s tidak ada di GRN. ', v_bill_line.item_id);
              CONTINUE;
            END IF;
            SELECT * INTO v_po_line FROM purchase_order_lines
            WHERE id = v_grn_line.purchase_order_line_id;

            IF v_bill_line.qty > v_grn_line.qty_accepted THEN
              v_mismatch_found := TRUE;
              v_mismatch_detail := v_mismatch_detail || format(
                'Qty bill (%s) melebihi qty accepted GRN (%s) untuk '
                'item %s. ', v_bill_line.qty, v_grn_line.qty_accepted,
                v_bill_line.item_id);
              CONTINUE;
            END IF;

            v_variance_pct := ABS(
              v_bill_line.unit_price - v_po_line.unit_price
            ) / NULLIF(v_po_line.unit_price, 0) * 100;
            IF v_variance_pct > p_tolerance_pct THEN
              v_mismatch_found := TRUE;
              v_mismatch_detail := v_mismatch_detail || format(
                'Selisih harga item %s: PO %s vs Bill %s (%s%%, '
                'toleransi %s%%). ', v_bill_line.item_id,
                v_po_line.unit_price, v_bill_line.unit_price,
                v_variance_pct, p_tolerance_pct);
            ELSE
              v_total_variance := v_total_variance
                + ROUND((v_bill_line.unit_price
                         - v_po_line.unit_price)
                        * v_bill_line.qty, 2);
            END IF;

            v_grir_amount := v_grir_amount
              + ROUND(v_bill_line.qty * v_po_line.unit_price, 2);
          END LOOP;

          IF v_mismatch_found THEN
            UPDATE ap_bills SET status = 'DISPUTED',
              dispute_reason = v_mismatch_detail
            WHERE id = p_ap_bill_id;
            RETURN jsonb_build_object('success', FALSE,
              'status', 'DISPUTED', 'reason', v_mismatch_detail);
          END IF;

          v_je_lines := jsonb_build_array(
            jsonb_build_object('account_id',
              (SELECT gl_grir_clearing_account_id
               FROM entity_gl_defaults
               WHERE entity_id = v_bill.entity_id),
              'debit_amount', v_grir_amount, 'credit_amount', 0),
            jsonb_build_object('account_id',
              (SELECT gl_ppn_masukan_account_id
               FROM entity_gl_defaults
               WHERE entity_id = v_bill.entity_id),
              'debit_amount', v_bill.tax_amount, 'credit_amount', 0),
            jsonb_build_object('account_id',
              (SELECT gl_ap_account_id FROM entity_gl_defaults
               WHERE entity_id = v_bill.entity_id),
              'debit_amount', 0, 'credit_amount', v_bill.total_amount)
          );
          IF v_total_variance <> 0 THEN
            v_je_lines := v_je_lines || jsonb_build_object(
              'account_id',
              (SELECT gl_price_variance_account_id
               FROM entity_gl_defaults
               WHERE entity_id = v_bill.entity_id),
              'debit_amount', GREATEST(v_total_variance, 0),
              'credit_amount', GREATEST(-v_total_variance, 0));
          END IF;

          v_je_result := fn_create_journal_entry(
            v_bill.entity_id, v_bill.bill_date,
            format('AP Bill Matched %s', v_bill.bill_number),
            'IDR', v_je_lines);
          PERFORM fn_post_journal_entry(
            (v_je_result->>'journal_entry_id')::uuid);

          UPDATE ap_bills SET status = 'APPROVED',
            journal_entry_id =
              (v_je_result->>'journal_entry_id')::uuid
          WHERE id = p_ap_bill_id;

          RETURN jsonb_build_object('success', TRUE,
            'status', 'APPROVED', 'price_variance', v_total_variance);
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 8: fn_record_ap_payment — Dr AP / Cr Kas-Bank, FIFO allocate
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_record_ap_payment(
          p_vendor_id UUID,
          p_payment_date DATE,
          p_amount NUMERIC,
          p_payment_method VARCHAR,
          p_allocations JSONB DEFAULT NULL
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_entity_id   UUID;
          v_ap_account  UUID;
          v_cash_account UUID;
          v_amount      NUMERIC(18,2);
          v_remaining   NUMERIC(18,2) := 0;
          v_alloc       JSONB;
          v_bill        RECORD;
          v_take        NUMERIC(18,2);
          v_je_result   JSONB;
          v_payment_id  UUID;
        BEGIN
          IF fn_current_role() NOT IN
             ('FINANCE_OPERATOR','DEPT_HEAD_FA','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only finance staff can record AP payments.');
          END IF;

          SELECT entity_id INTO v_entity_id FROM vendors
          WHERE id = p_vendor_id;
          IF v_entity_id IS NULL THEN
            PERFORM fn_raise_error('VENDOR_NOT_FOUND',
              'Vendor tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_entity_id THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only pay vendors of your own entity.');
          END IF;

          SELECT gl_ap_account_id, gl_kas_bank_default_account_id
          INTO v_ap_account, v_cash_account
          FROM entity_gl_defaults WHERE entity_id = v_entity_id;
          IF v_ap_account IS NULL OR v_cash_account IS NULL THEN
            PERFORM fn_raise_error('GL_DEFAULTS_MISSING',
              'Entity GL defaults (AP/cash) belum dikonfigurasi.');
          END IF;

          v_amount := ROUND(p_amount, 2);
          IF v_amount <= 0 THEN
            PERFORM fn_raise_error('INVALID_AMOUNT',
              'Jumlah pembayaran harus > 0.');
          END IF;

          INSERT INTO ap_payments
            (entity_id, vendor_id, payment_date, amount,
             payment_method, created_by)
          VALUES (v_entity_id, p_vendor_id, p_payment_date, v_amount,
            p_payment_method, fn_current_user_id())
          RETURNING id INTO v_payment_id;

          v_remaining := v_amount;
          IF p_allocations IS NOT NULL
             AND jsonb_array_length(p_allocations) > 0 THEN
            FOR v_alloc IN
              SELECT * FROM jsonb_array_elements(p_allocations)
            LOOP
              v_take := LEAST(
                (v_alloc->>'amount')::numeric, v_remaining);
              v_take := LEAST(v_take,
                (SELECT total_amount - paid_amount FROM ap_bills
                 WHERE id = (v_alloc->>'bill_id')::uuid));
              IF v_take > 0 THEN
                INSERT INTO ap_payment_allocations
                  (ap_payment_id, ap_bill_id, allocated_amount)
                VALUES (v_payment_id,
                  (v_alloc->>'bill_id')::uuid, v_take);
                UPDATE ap_bills
                SET paid_amount = paid_amount + v_take,
                    status = (CASE
                      WHEN paid_amount + v_take >= total_amount
                      THEN 'PAID' ELSE 'APPROVED'
                    END)::ap_bill_status_enum
                WHERE id = (v_alloc->>'bill_id')::uuid;
                v_remaining := v_remaining - v_take;
              END IF;
            END LOOP;
          ELSE
            FOR v_bill IN
              SELECT id, total_amount - paid_amount AS outstanding
              FROM ap_bills
              WHERE vendor_id = p_vendor_id
                AND status = 'APPROVED'
              ORDER BY due_date, bill_number
            LOOP
              EXIT WHEN v_remaining <= 0;
              v_take := LEAST(v_remaining, v_bill.outstanding);
              IF v_take > 0 THEN
                INSERT INTO ap_payment_allocations
                  (ap_payment_id, ap_bill_id, allocated_amount)
                VALUES (v_payment_id, v_bill.id, v_take);
                UPDATE ap_bills
                SET paid_amount = paid_amount + v_take,
                    status = (CASE
                      WHEN paid_amount + v_take >= total_amount
                      THEN 'PAID' ELSE 'APPROVED'
                    END)::ap_bill_status_enum
                WHERE id = v_bill.id;
                v_remaining := v_remaining - v_take;
              END IF;
            END LOOP;
          END IF;

          v_je_result := fn_create_journal_entry(
            v_entity_id, p_payment_date,
            format('AP Payment vendor %s', p_vendor_id),
            'IDR',
            jsonb_build_array(
              jsonb_build_object('account_id', v_ap_account,
                'debit_amount', v_amount, 'credit_amount', 0),
              jsonb_build_object('account_id', v_cash_account,
                'debit_amount', 0, 'credit_amount', v_amount)
            ));
          PERFORM fn_post_journal_entry(
            (v_je_result->>'journal_entry_id')::uuid);
          UPDATE ap_payments
          SET journal_entry_id =
            (v_je_result->>'journal_entry_id')::uuid
          WHERE id = v_payment_id;

          RETURN jsonb_build_object('success', TRUE,
            'ap_payment_id', v_payment_id,
            'journal_entry_id',
            (v_je_result->>'journal_entry_id')::uuid);
        END;
        $$;
        """
    )



def downgrade() -> None:
    for fn in (
        "fn_record_ap_payment",
        "fn_match_and_approve_ap_bill",
        "fn_create_ap_bill",
        "fn_inspect_grn",
        "fn_receive_goods",
        "fn_approve_purchase_order",
        "fn_submit_purchase_order",
        "fn_get_required_approval_role",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")
    op.execute("DROP TABLE IF EXISTS ap_payment_allocations CASCADE")
    op.execute("DROP TABLE IF EXISTS ap_payments CASCADE")
    op.execute("DROP TABLE IF EXISTS ap_bill_lines CASCADE")
    op.execute("DROP TABLE IF EXISTS ap_bills CASCADE")
    op.execute("DROP TABLE IF EXISTS grn_lines CASCADE")
    op.execute("DROP TABLE IF EXISTS goods_received_notes CASCADE")
    op.execute("DROP TABLE IF EXISTS purchase_order_lines CASCADE")
    op.execute("DROP TABLE IF EXISTS purchase_orders CASCADE")
    op.execute("DROP TABLE IF EXISTS purchase_request_lines CASCADE")
    op.execute("DROP TABLE IF EXISTS purchase_requests CASCADE")
    op.execute("DROP TABLE IF EXISTS vendors CASCADE")
    op.execute("DROP TABLE IF EXISTS approval_thresholds CASCADE")
    for col in (
        "gl_price_variance_account_id",
        "gl_grir_clearing_account_id",
        "gl_ppn_masukan_account_id",
        "gl_ap_account_id",
    ):
        op.execute(
            "ALTER TABLE entity_gl_defaults DROP COLUMN IF EXISTS "
            + col
        )
    for type_ in (
        "approval_doc_type_enum",
        "ap_bill_status_enum",
        "inspection_status_enum",
        "grn_status_enum",
        "po_status_enum",
        "pr_status_enum",
    ):
        op.execute(f"DROP TYPE IF EXISTS {type_} CASCADE")
