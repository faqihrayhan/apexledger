"""Add Modul 5A: Purchase Return (Debit Note) & Landed Cost

Revision ID: f3a5c7d91b42
Revises: e8b1d4f73a29
Create Date: 2026-08-31

(A) Purchase Return: barang rusak/ Salah kirim diretur ke vendor
    (debit note) — issue stock out, kurangi AP, GL Dr AP /
    Cr Inventory / Cr PPN Masukan.
(B) Landed Cost: freight/customs/insurance dialokasikan ke GRN
    untuk mengkapitalisasi HPP (BY_VALUE / BY_QTY / BY_WEIGHT).

Adaptasi dialek lokal: auth.uid() -> fn_current_user_id(),
auth.users -> user_profiles.

CASE literal -> enum WAJIB cast eksplisit (aturan repo).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f3a5c7d91b42"
down_revision = "e8b1d4f73a29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enums
    # ------------------------------------------------------------------
    op.execute(
        "CREATE TYPE purchase_return_status_enum AS ENUM "
        "('DRAFT','APPROVED','CANCELLED')"
    )
    op.execute(
        "CREATE TYPE landed_cost_alloc_method_enum AS ENUM "
        "('BY_VALUE','BY_QTY','BY_WEIGHT')"
    )
    op.execute(
        "CREATE TYPE landed_cost_status_enum AS ENUM "
        "('DRAFT','ALLOCATED','CANCELLED')"
    )

    # ------------------------------------------------------------------
    # entity_gl_defaults: landed cost clearing account
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE entity_gl_defaults "
        "ADD COLUMN gl_landed_cost_clearing_account_id UUID "
        "REFERENCES chart_of_accounts(id)"
    )

    # ------------------------------------------------------------------
    # purchase_returns + lines
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE purchase_returns (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          vendor_id UUID NOT NULL REFERENCES vendors(id),
          grn_id UUID NOT NULL REFERENCES goods_received_notes(id),
          warehouse_id UUID NOT NULL REFERENCES warehouses(id),
          return_number VARCHAR(30) NOT NULL,
          return_date DATE NOT NULL,
          status purchase_return_status_enum NOT NULL DEFAULT 'DRAFT',
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
        CREATE TABLE purchase_return_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          purchase_return_id UUID NOT NULL REFERENCES
            purchase_returns(id) ON DELETE CASCADE,
          grn_line_id UUID NOT NULL REFERENCES grn_lines(id),
          item_id UUID NOT NULL REFERENCES items(id),
          qty_returned NUMERIC(18,4) NOT NULL CHECK (qty_returned > 0),
          unit_price NUMERIC(18,2) NOT NULL,
          line_total NUMERIC(18,2) NOT NULL
        )
        """
    )

    op.execute(
        "ALTER TABLE purchase_returns ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY pur_select_scoped ON purchase_returns
        FOR SELECT USING (
          entity_id = fn_current_entity_id()
          OR fn_current_role() IN ('SUPER_ADMIN','IT_ADMIN')
        )
        """
    )
    op.execute(
        """
        CREATE POLICY pur_insert_scoped ON purchase_returns
        FOR INSERT WITH CHECK (
          entity_id = fn_current_entity_id()
          AND fn_current_role() IN (
            'WAREHOUSE_OPERATOR','DEPT_HEAD_WAREHOUSE',
            'FINANCE_OPERATOR','SUPER_ADMIN')
        )
        """
    )
    op.execute(
        "REVOKE UPDATE, DELETE ON purchase_returns FROM PUBLIC"
    )
    op.execute(
        "ALTER TABLE purchase_return_lines ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY purl_select_scoped ON purchase_return_lines
        FOR SELECT USING (
          purchase_return_id IN (SELECT id FROM purchase_returns)
        )
        """
    )

    # ------------------------------------------------------------------
    # landed_costs + lines
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE landed_costs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          grn_id UUID NOT NULL REFERENCES goods_received_notes(id),
          lc_number VARCHAR(30) NOT NULL,
          lc_date DATE NOT NULL,
          vendor_id UUID REFERENCES vendors(id),
          description TEXT NOT NULL,
          total_amount NUMERIC(18,2) NOT NULL
            CHECK (total_amount > 0),
          allocation_method landed_cost_alloc_method_enum
            NOT NULL DEFAULT 'BY_VALUE',
          status landed_cost_status_enum NOT NULL DEFAULT 'DRAFT',
          journal_entry_id UUID REFERENCES journal_entries(id),
          created_by UUID NOT NULL REFERENCES user_profiles(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entity_id, lc_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE landed_cost_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          landed_cost_id UUID NOT NULL REFERENCES
            landed_costs(id) ON DELETE CASCADE,
          grn_line_id UUID NOT NULL REFERENCES grn_lines(id),
          item_id UUID NOT NULL REFERENCES items(id),
          allocated_amount NUMERIC(18,2) NOT NULL
            CHECK (allocated_amount >= 0)
        )
        """
    )

    op.execute(
        "ALTER TABLE landed_costs ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY lc_select_scoped ON landed_costs
        FOR SELECT USING (
          entity_id = fn_current_entity_id()
          OR fn_current_role() IN ('SUPER_ADMIN','IT_ADMIN')
        )
        """
    )
    op.execute(
        """
        CREATE POLICY lc_insert_scoped ON landed_costs
        FOR INSERT WITH CHECK (
          entity_id = fn_current_entity_id()
          AND fn_current_role() IN (
            'FINANCE_OPERATOR','DEPT_HEAD_FA','SUPER_ADMIN')
        )
        """
    )
    op.execute(
        "REVOKE UPDATE, DELETE ON landed_costs FROM PUBLIC"
    )
    op.execute(
        "ALTER TABLE landed_cost_lines ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY lcl_select_scoped ON landed_cost_lines
        FOR SELECT USING (
          landed_cost_id IN (SELECT id FROM landed_costs)
        )
        """
    )

    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # RPC 1: fn_approve_purchase_return — debit note (Dr AP /
    # Cr Inventory / Cr PPN Masukan), issue stock out, kurangi AP
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_approve_purchase_return(
            p_purchase_return_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
            v_ret          purchase_returns%ROWTYPE;
            v_line         RECORD;
            v_grn          goods_received_notes%ROWTYPE;
            v_subtotal     NUMERIC(18,2) := 0;
            v_tax_rate_pct NUMERIC;
            v_tax_amount   NUMERIC(18,2);
            v_total_amount NUMERIC(18,2);
            v_issue_result JSONB;
            v_je_lines     JSONB;
            v_je_result    JSONB;
        BEGIN
            SELECT * INTO v_ret FROM purchase_returns
              WHERE id = p_purchase_return_id FOR UPDATE;
            IF NOT FOUND THEN
                PERFORM fn_raise_error('RETURN_NOT_FOUND',
                    'Purchase return tidak ditemukan.');
            END IF;
            IF v_ret.status <> 'DRAFT' THEN
                PERFORM fn_raise_error('RETURN_INVALID_STATUS',
                    format('Purchase return berstatus %s, '
                           'hanya DRAFT yang dapat di-approve.',
                           v_ret.status));
            END IF;

            SELECT * INTO v_grn FROM goods_received_notes
              WHERE id = v_ret.grn_id;

            FOR v_line IN
              SELECT * FROM purchase_return_lines
                WHERE purchase_return_id = p_purchase_return_id
            LOOP
                -- Validasi: qty retur <= qty accepted di GRN.
                IF v_line.qty_returned >
                   (SELECT qty_accepted FROM grn_lines
                     WHERE id = v_line.grn_line_id) THEN
                    PERFORM fn_raise_error(
                        'RETURN_QTY_EXCEEDS_ACCEPTED',
                        format('Qty retur (%s) melebihi qty '
                               'accepted GRN untuk item %s.',
                               v_line.qty_returned,
                               v_line.item_id));
                END IF;

                -- Keluarkan stok dari gudang @ avg_cost.
                v_issue_result := fn_issue_stock(
                    v_line.item_id, v_ret.warehouse_id,
                    v_line.qty_returned, 'PURCHASE_RETURN',
                    p_purchase_return_id);

                v_subtotal := v_subtotal + v_line.line_total;
            END LOOP;

            -- Pajak: derive dari AP bill GRN tsb, default 11%.
            v_tax_rate_pct := COALESCE(
                (SELECT CASE WHEN b.subtotal > 0 THEN
                    ROUND(b.tax_amount / b.subtotal * 100, 2)
                 ELSE 0 END
                 FROM ap_bills b
                 WHERE b.grn_id = v_ret.grn_id
                   AND b.status IN ('APPROVED','PAID')
                 LIMIT 1),
                11
            );
            v_tax_amount :=
                ROUND(v_subtotal * v_tax_rate_pct / 100, 2);
            v_total_amount := v_subtotal + v_tax_amount;

            UPDATE purchase_returns SET
                subtotal = v_subtotal,
                tax_amount = v_tax_amount,
                total_amount = v_total_amount,
                status = 'APPROVED',
                approved_by = fn_current_user_id(),
                approved_at = now()
            WHERE id = p_purchase_return_id;

            -- GL debit note:
            -- Dr AP / Cr Inventory per item / Cr PPN Masukan.
            v_je_lines := jsonb_build_array(
                jsonb_build_object(
                    'account_id',
                    (SELECT gl_ap_account_id FROM entity_gl_defaults
                     WHERE entity_id = v_ret.entity_id),
                    'debit_amount', v_total_amount,
                    'credit_amount', 0,
                    'description', format(
                        'Debit Note %s — reduce AP vendor',
                        v_ret.return_number)
                ),
                jsonb_build_object(
                    'account_id',
                    (SELECT gl_ppn_masukan_account_id
                     FROM entity_gl_defaults
                     WHERE entity_id = v_ret.entity_id),
                    'debit_amount', 0,
                    'credit_amount', v_tax_amount,
                    'description',
                      'Reversal PPN Masukan — purchase return')
            );

            FOR v_line IN
              SELECT prl.item_id, i.gl_inventory_account_id,
                     prl.line_total
              FROM purchase_return_lines prl
                JOIN items i ON i.id = prl.item_id
              WHERE prl.purchase_return_id = p_purchase_return_id
            LOOP
                IF v_line.gl_inventory_account_id IS NULL THEN
                    PERFORM fn_raise_error(
                        'ITEM_INVENTORY_ACCOUNT_MISSING',
                        format('Item %s belum punya '
                               'gl_inventory_account_id.',
                               v_line.item_id));
                END IF;
                v_je_lines := v_je_lines || jsonb_build_object(
                    'account_id', v_line.gl_inventory_account_id,
                    'debit_amount', 0,
                    'credit_amount', v_line.line_total,
                    'description', format(
                        'Inventory out — purchase return item %s',
                        v_line.item_id)
                );
            END LOOP;

            v_je_result := fn_create_journal_entry(
                v_ret.entity_id, v_ret.return_date,
                format('Purchase Return / Debit Note %s',
                       v_ret.return_number),
                'IDR', v_je_lines);
            PERFORM fn_post_journal_entry(
                (v_je_result->>'journal_entry_id')::uuid);

            UPDATE purchase_returns
              SET journal_entry_id =
                    (v_je_result->>'journal_entry_id')::uuid
              WHERE id = p_purchase_return_id;

            -- Kurangi outstanding AP bill (jika ada yang approved).
            UPDATE ap_bills SET
                paid_amount = paid_amount + v_total_amount,
                status = (CASE
                    WHEN paid_amount + v_total_amount
                         >= total_amount THEN 'PAID'
                    ELSE status END)::ap_bill_status_enum
            WHERE grn_id = v_ret.grn_id
              AND status IN ('APPROVED','PAID');

            INSERT INTO system_logs(
                actor_id, entity_id, action, table_name,
                record_id, after_data)
            VALUES (
                fn_current_user_id(), v_ret.entity_id, 'APPROVE',
                'purchase_returns', p_purchase_return_id::text,
                jsonb_build_object(
                    'return_number', v_ret.return_number,
                    'total_amount', v_total_amount));

            RETURN jsonb_build_object(
                'purchase_return_id', p_purchase_return_id,
                'return_number', v_ret.return_number,
                'subtotal', v_subtotal,
                'tax_amount', v_tax_amount,
                'total_amount', v_total_amount,
                'journal_entry_id',
                  (v_je_result->>'journal_entry_id')::uuid);
        END;
        $$;
        """
    )


    # ------------------------------------------------------------------
    # RPC 2: fn_allocate_landed_cost — distribute freight/customs/
    # insurance ke GRN items, capitalize avg_cost, GL Dr Inv / Cr LC
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_allocate_landed_cost(
            p_landed_cost_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
            v_lc           landed_costs%ROWTYPE;
            v_grn          goods_received_notes%ROWTYPE;
            v_grn_line     RECORD;
            v_total_basis  NUMERIC(18,4) := 0;
            v_alloc_amount NUMERIC(18,2);
            v_alloc_sum    NUMERIC(18,2) := 0;
            v_line_count   INT := 0;
            v_total_lines  INT;
            v_je_lines     JSONB;
            v_je_result    JSONB;
            v_inv_entries  JSONB := '[]'::jsonb;
        BEGIN
            SELECT * INTO v_lc FROM landed_costs
              WHERE id = p_landed_cost_id FOR UPDATE;
            IF NOT FOUND THEN
                PERFORM fn_raise_error('LC_NOT_FOUND',
                    'Landed cost record tidak ditemukan.');
            END IF;
            IF v_lc.status <> 'DRAFT' THEN
                PERFORM fn_raise_error('LC_INVALID_STATUS',
                    format('Landed cost berstatus %s, '
                           'hanya DRAFT yang dapat dialokasi.',
                           v_lc.status));
            END IF;

            SELECT * INTO v_grn FROM goods_received_notes
              WHERE id = v_lc.grn_id;
            IF v_grn.status <> 'COMPLETED' THEN
                PERFORM fn_raise_error('GRN_NOT_COMPLETED',
                    'GRN harus berstatus COMPLETED sebelum '
                    'alokasi landed cost.');
            END IF;

            SELECT COUNT(*) INTO v_total_lines FROM grn_lines
              WHERE grn_id = v_lc.grn_id AND qty_accepted > 0;
            IF v_total_lines = 0 THEN
                PERFORM fn_raise_error('GRN_NO_ACCEPTED_LINES',
                    'GRN tidak memiliki baris accepted.');
            END IF;

            -- Basis alokasi.
            FOR v_grn_line IN
              SELECT gl.*, pol.unit_price AS po_unit_price
              FROM grn_lines gl
                JOIN purchase_order_lines pol
                  ON pol.id = gl.purchase_order_line_id
              WHERE gl.grn_id = v_lc.grn_id
                AND gl.qty_accepted > 0
            LOOP
                CASE v_lc.allocation_method
                    WHEN 'BY_VALUE' THEN v_total_basis :=
                        v_total_basis + (v_grn_line.qty_accepted
                          * v_grn_line.po_unit_price);
                    WHEN 'BY_QTY' THEN v_total_basis :=
                        v_total_basis + v_grn_line.qty_accepted;
                    WHEN 'BY_WEIGHT' THEN v_total_basis :=
                        v_total_basis + v_grn_line.qty_accepted;
                END CASE;
            END LOOP;

            IF v_total_basis <= 0 THEN
                PERFORM fn_raise_error('LC_ZERO_BASIS',
                    'Total allocation basis is zero.');
            END IF;

            -- Alokasi + kapitalisasi.
            FOR v_grn_line IN
              SELECT gl.*, pol.unit_price AS po_unit_price,
                     i.gl_inventory_account_id
              FROM grn_lines gl
                JOIN purchase_order_lines pol
                  ON pol.id = gl.purchase_order_line_id
                JOIN items i ON i.id = gl.item_id
              WHERE gl.grn_id = v_lc.grn_id
                AND gl.qty_accepted > 0
              ORDER BY gl.id
            LOOP
                v_line_count := v_line_count + 1;

                IF v_line_count = v_total_lines THEN
                    v_alloc_amount :=
                        v_lc.total_amount - v_alloc_sum;
                ELSE
                    CASE v_lc.allocation_method
                        WHEN 'BY_VALUE' THEN v_alloc_amount := ROUND(
                            v_lc.total_amount
                              * (v_grn_line.qty_accepted
                                 * v_grn_line.po_unit_price)
                              / v_total_basis, 2);
                        WHEN 'BY_QTY' THEN v_alloc_amount := ROUND(
                            v_lc.total_amount
                              * v_grn_line.qty_accepted
                              / v_total_basis, 2);
                        WHEN 'BY_WEIGHT' THEN v_alloc_amount := ROUND(
                            v_lc.total_amount
                              * v_grn_line.qty_accepted
                              / v_total_basis, 2);
                    END CASE;
                END IF;
                v_alloc_sum := v_alloc_sum + v_alloc_amount;

                INSERT INTO landed_cost_lines (
                    landed_cost_id, grn_line_id, item_id,
                    allocated_amount)
                VALUES (p_landed_cost_id, v_grn_line.id,
                        v_grn_line.item_id, v_alloc_amount);

                -- Kapitalisasi HPP: naikkan avg_cost.
                UPDATE item_warehouse_stock SET
                    avg_cost = ROUND(
                        (avg_cost * qty_on_hand + v_alloc_amount)
                        / NULLIF(qty_on_hand, 0), 4)
                WHERE item_id = v_grn_line.item_id
                  AND warehouse_id = v_grn.warehouse_id
                  AND qty_on_hand > 0;

                -- Audit trail stok (qty 0, biaya tambahan).
                INSERT INTO stock_transactions (
                    item_id, warehouse_id, transaction_type,
                    qty, unit_cost, total_cost,
                    reference_type, reference_id, created_by)
                VALUES (v_grn_line.item_id, v_grn.warehouse_id,
                        'ADJUSTMENT', 0,
                        ROUND(v_alloc_amount
                          / NULLIF(v_grn_line.qty_accepted, 0), 4),
                        v_alloc_amount,
                        'LANDED_COST', p_landed_cost_id,
                        fn_current_user_id());

                IF v_grn_line.gl_inventory_account_id IS NULL THEN
                    PERFORM fn_raise_error(
                        'ITEM_INVENTORY_ACCOUNT_MISSING',
                        format('Item %s belum punya '
                               'gl_inventory_account_id.',
                               v_grn_line.item_id));
                END IF;
                v_inv_entries := v_inv_entries
                  || jsonb_build_object(
                        'account_id',
                        v_grn_line.gl_inventory_account_id,
                        'debit_amount', v_alloc_amount,
                        'credit_amount', 0,
                        'description', format(
                          'Landed cost allocation — item %s',
                          v_grn_line.item_id));
            END LOOP;

            -- GL: Dr Inventory per item / Cr LC clearing
            -- (fallback AP).
            v_je_lines := v_inv_entries || jsonb_build_object(
                'account_id', COALESCE(
                    (SELECT gl_landed_cost_clearing_account_id
                     FROM entity_gl_defaults
                     WHERE entity_id = v_lc.entity_id),
                    (SELECT gl_ap_account_id FROM entity_gl_defaults
                     WHERE entity_id = v_lc.entity_id)),
                'debit_amount', 0,
                'credit_amount', v_lc.total_amount,
                'description', format('Landed Cost %s — %s',
                    v_lc.lc_number, v_lc.description));

            v_je_result := fn_create_journal_entry(
                v_lc.entity_id, v_lc.lc_date,
                format('Landed Cost Allocation %s', v_lc.lc_number),
                'IDR', v_je_lines);
            PERFORM fn_post_journal_entry(
                (v_je_result->>'journal_entry_id')::uuid);

            UPDATE landed_costs SET status = 'ALLOCATED',
                journal_entry_id =
                    (v_je_result->>'journal_entry_id')::uuid
            WHERE id = p_landed_cost_id;

            INSERT INTO system_logs(
                actor_id, entity_id, action, table_name,
                record_id, after_data)
            VALUES (
                fn_current_user_id(), v_lc.entity_id, 'ALLOCATE',
                'landed_costs', p_landed_cost_id::text,
                jsonb_build_object(
                    'lc_number', v_lc.lc_number,
                    'total_amount', v_lc.total_amount,
                    'method', v_lc.allocation_method::text));

            RETURN jsonb_build_object(
                'landed_cost_id', p_landed_cost_id,
                'lc_number', v_lc.lc_number,
                'total_allocated', v_alloc_sum,
                'lines_count', v_line_count,
                'journal_entry_id',
                  (v_je_result->>'journal_entry_id')::uuid);
        END;
        $$;
        """
    )


    # --- end of RPC definitions ---
    # ------------------------------------------------------------------


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS lcl_select_scoped ON landed_cost_lines")
    op.execute("DROP TABLE IF EXISTS landed_cost_lines")
    op.execute("DROP POLICY IF EXISTS lc_insert_scoped ON landed_costs")
    op.execute("DROP POLICY IF EXISTS lc_select_scoped ON landed_costs")
    op.execute("DROP TABLE IF EXISTS landed_costs")
    op.execute("DROP POLICY IF EXISTS purl_select_scoped ON purchase_return_lines")
    op.execute("DROP TABLE IF EXISTS purchase_return_lines")
    op.execute("DROP POLICY IF EXISTS pur_insert_scoped ON purchase_returns")
    op.execute("DROP POLICY IF EXISTS pur_select_scoped ON purchase_returns")
    op.execute("DROP TABLE IF EXISTS purchase_returns")
    op.execute(
        "ALTER TABLE entity_gl_defaults "
        "DROP COLUMN IF EXISTS gl_landed_cost_clearing_account_id"
    )
    op.execute("DROP TYPE IF EXISTS landed_cost_status_enum")
    op.execute("DROP TYPE IF EXISTS landed_cost_alloc_method_enum")
    op.execute("DROP TYPE IF EXISTS purchase_return_status_enum")
