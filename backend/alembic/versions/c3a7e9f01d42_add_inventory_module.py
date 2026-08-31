"""Add Modul 3: Universal Costing & Inventory

Revision ID: c3a7e9f01d42
Revises: 8f4d2c1b7a9e
Create Date: 2026-08-30

Tables (9): warehouses, items, stock_lots, item_warehouse_stock,
stock_transactions, boms, bom_components, cost_centers, work_orders.

RPCs (4): fn_receive_stock (moving-average recompute + FEFO lots),
fn_issue_stock (anti-negative, FIFO/FEFO layer consumption),
fn_transfer_stock (atomic cross-warehouse), fn_complete_work_order
(BOM consumption + COGM + FOH allocation + auto-posting GL).

Costing rules (PRD Modul 3):
- MOVING_AVERAGE: avg_cost recomputed per receipt (weighted average).
- FIFO/FEFO: lot layer consumption, oldest first (FEFO = nearest
  expiry first). Expired lots are never consumed; aggregate-vs-lot
  drift is rejected with LOT_STOCK_DRIFT (needs stock opname).
- Anti-negative stock enforced at the aggregate before layer burn.
- COGM = direct materials + direct labor + allocated FOH;
  FOH rate = estimated overhead / capacity driver.
- BOM consumption qty = qty_per_yield x (qty_produced / yield_qty)
  x (1 + waste_pct/100).
"""

from alembic import op

revision = "c3a7e9f01d42"
down_revision = "8f4d2c1b7a9e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enums
    # ------------------------------------------------------------------
    op.execute(
        "CREATE TYPE item_type_enum AS ENUM "
        "('RAW_MATERIAL','FINISHED_GOOD','SERVICE','BUNDLE')"
    )
    op.execute(
        "CREATE TYPE costing_method_enum AS ENUM ('FIFO','MOVING_AVERAGE')"
    )
    op.execute(
        "CREATE TYPE stock_txn_type_enum AS ENUM "
        "('RECEIPT','ISSUE','TRANSFER_OUT','TRANSFER_IN','ADJUSTMENT',"
        "'WO_CONSUMPTION','WO_OUTPUT')"
    )
    op.execute(
        "CREATE TYPE wo_status_enum AS ENUM "
        "('DRAFT','IN_PROGRESS','COMPLETED','CLOSED')"
    )
    op.execute(
        "CREATE TYPE bom_type_enum AS ENUM ('RECIPE','KIT','ROUTING')"
    )

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE warehouses (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          code VARCHAR(20) NOT NULL,
          name VARCHAR(100) NOT NULL,
          warehouse_type VARCHAR(20) NOT NULL DEFAULT 'OUTLET' CHECK
            (warehouse_type IN ('CENTRAL_KITCHEN','OUTLET','WAREHOUSE')),
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entity_id, code)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE items (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          item_code VARCHAR(30) NOT NULL,
          item_name VARCHAR(150) NOT NULL,
          item_type item_type_enum NOT NULL,
          costing_method costing_method_enum NOT NULL DEFAULT 'MOVING_AVERAGE',
          uom_base VARCHAR(10) NOT NULL,
          requires_fefo BOOLEAN NOT NULL DEFAULT FALSE,
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          gl_inventory_account_id UUID REFERENCES chart_of_accounts(id),
          gl_cogs_account_id UUID REFERENCES chart_of_accounts(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entity_id, item_code)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE stock_lots (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          item_id UUID NOT NULL REFERENCES items(id),
          warehouse_id UUID NOT NULL REFERENCES warehouses(id),
          lot_number VARCHAR(30),
          qty_received NUMERIC(18,4) NOT NULL CHECK (qty_received > 0),
          qty_remaining NUMERIC(18,4) NOT NULL CHECK (qty_remaining >= 0),
          unit_cost NUMERIC(18,4) NOT NULL CHECK (unit_cost >= 0),
          received_date TIMESTAMPTZ NOT NULL DEFAULT now(),
          expiry_date DATE
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_stock_lots_fifo ON stock_lots"
        "(item_id, warehouse_id, received_date) WHERE qty_remaining > 0"
    )
    op.execute(
        "CREATE INDEX idx_stock_lots_fefo ON stock_lots"
        "(item_id, warehouse_id, expiry_date) WHERE qty_remaining > 0"
    )
    op.execute(
        """
        CREATE TABLE item_warehouse_stock (
          item_id UUID NOT NULL REFERENCES items(id),
          warehouse_id UUID NOT NULL REFERENCES warehouses(id),
          qty_on_hand NUMERIC(18,4) NOT NULL DEFAULT 0,
          avg_cost NUMERIC(18,4) NOT NULL DEFAULT 0,
          PRIMARY KEY (item_id, warehouse_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE stock_transactions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          item_id UUID NOT NULL REFERENCES items(id),
          warehouse_id UUID NOT NULL REFERENCES warehouses(id),
          transaction_type stock_txn_type_enum NOT NULL,
          qty NUMERIC(18,4) NOT NULL,
          unit_cost NUMERIC(18,4) NOT NULL,
          total_cost NUMERIC(18,2) NOT NULL,
          reference_type VARCHAR(30),
          reference_id UUID,
          transaction_date TIMESTAMPTZ NOT NULL DEFAULT now(),
          created_by UUID NOT NULL REFERENCES user_profiles(id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE boms (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          item_id UUID NOT NULL REFERENCES items(id),
          bom_type bom_type_enum NOT NULL,
          version INT NOT NULL DEFAULT 1,
          yield_qty NUMERIC(18,4) NOT NULL DEFAULT 1,
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (item_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE bom_components (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          bom_id UUID NOT NULL REFERENCES boms(id) ON DELETE CASCADE,
          component_item_id UUID NOT NULL REFERENCES items(id),
          qty_per_yield NUMERIC(18,4) NOT NULL CHECK (qty_per_yield > 0),
          waste_pct NUMERIC(5,2) NOT NULL DEFAULT 0 CHECK
            (waste_pct >= 0 AND waste_pct < 100),
          sequence_no SMALLINT NOT NULL DEFAULT 1
        )
        """
    )
    op.execute(
        """
        CREATE TABLE cost_centers (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          code VARCHAR(20) NOT NULL,
          name VARCHAR(100) NOT NULL,
          total_estimated_overhead NUMERIC(18,2) NOT NULL DEFAULT 0,
          total_capacity_driver NUMERIC(18,4) NOT NULL DEFAULT 0,
          driver_unit VARCHAR(20) NOT NULL DEFAULT 'LABOR_HOURS',
          gl_foh_applied_account_id UUID REFERENCES chart_of_accounts(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entity_id, code)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE work_orders (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          wo_number VARCHAR(30) NOT NULL,
          bom_id UUID NOT NULL REFERENCES boms(id),
          item_id UUID NOT NULL REFERENCES items(id),
          warehouse_id UUID NOT NULL REFERENCES warehouses(id),
          cost_center_id UUID REFERENCES cost_centers(id),
          qty_planned NUMERIC(18,4) NOT NULL CHECK (qty_planned > 0),
          qty_produced NUMERIC(18,4),
          direct_labor_cost NUMERIC(18,2) NOT NULL DEFAULT 0,
          gl_accrued_labor_account_id UUID REFERENCES chart_of_accounts(id),
          driver_qty_used NUMERIC(18,4) NOT NULL DEFAULT 0,
          status wo_status_enum NOT NULL DEFAULT 'DRAFT',
          journal_entry_id UUID REFERENCES journal_entries(id),
          created_by UUID NOT NULL REFERENCES user_profiles(id),
          completed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entity_id, wo_number)
        )
        """
    )

    # ------------------------------------------------------------------
    # RLS — every table entity-scoped; stock_transactions SELECT
    # scoped to warehouses of the caller's entity.
    # ------------------------------------------------------------------
    for table in (
        "warehouses", "items", "boms", "bom_components",
        "cost_centers", "work_orders",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY warehouses_entity_policy ON warehouses FOR ALL USING (
          entity_id = fn_current_entity_id()
        )
        """
    )
    op.execute(
        """
        CREATE POLICY items_entity_policy ON items FOR ALL USING (
          entity_id = fn_current_entity_id()
        )
        """
    )
    op.execute(
        """
        CREATE POLICY boms_entity_policy ON boms FOR ALL USING (
          entity_id = fn_current_entity_id()
        )
        """
    )
    op.execute(
        """
        CREATE POLICY bom_components_entity_policy ON bom_components
        FOR ALL USING (
          EXISTS (
            SELECT 1 FROM boms b
            WHERE b.id = bom_components.bom_id
              AND b.entity_id = fn_current_entity_id()
          )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY cost_centers_entity_policy ON cost_centers FOR ALL
        USING (entity_id = fn_current_entity_id())
        """
    )
    op.execute(
        """
        CREATE POLICY work_orders_entity_policy ON work_orders FOR ALL
        USING (entity_id = fn_current_entity_id())
        """
    )
    op.execute("ALTER TABLE stock_transactions ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY stx_select_scoped ON stock_transactions FOR SELECT USING (
          warehouse_id IN (
            SELECT id FROM warehouses
            WHERE entity_id = fn_current_entity_id()
          )
          OR fn_current_role() IN ('SUPER_ADMIN','IT_ADMIN')
        )
        """
    )
    op.execute(
        "REVOKE UPDATE, DELETE ON stock_transactions, work_orders FROM PUBLIC"
    )

    # ------------------------------------------------------------------
    # RPC: fn_receive_stock
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_receive_stock(
          p_item_id UUID, p_warehouse_id UUID, p_qty NUMERIC,
          p_unit_cost NUMERIC, p_reference_type VARCHAR,
          p_reference_id UUID, p_expiry_date DATE DEFAULT NULL
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_item items%ROWTYPE;
          v_current_stock item_warehouse_stock%ROWTYPE;
          v_new_avg_cost NUMERIC(18,4);
          v_txn_id UUID;
        BEGIN
          IF fn_current_role() NOT IN
             ('WAREHOUSE_OPERATOR','DEPT_HEAD_WAREHOUSE',
              'FINANCE_OPERATOR','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only warehouse/finance roles can receive stock.');
          END IF;

          IF p_qty <= 0 THEN
            PERFORM fn_raise_error('INVALID_QTY',
              'Qty penerimaan harus lebih dari 0.');
          END IF;

          SELECT * INTO v_item FROM items
          WHERE id = p_item_id AND is_active = TRUE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('ITEM_NOT_FOUND',
              'Item tidak ditemukan atau nonaktif.');
          END IF;

          IF fn_current_entity_id() IS DISTINCT FROM v_item.entity_id THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'Stock moves must stay within your own entity.');
          END IF;

          IF v_item.requires_fefo AND p_expiry_date IS NULL THEN
            PERFORM fn_raise_error('EXPIRY_DATE_REQUIRED',
              'Item ini wajib FEFO — expiry harus diisi saat penerimaan.');
          END IF;

          INSERT INTO stock_lots
            (item_id, warehouse_id, qty_received, qty_remaining,
             unit_cost, expiry_date)
          VALUES
            (p_item_id, p_warehouse_id, p_qty, p_qty, p_unit_cost,
             p_expiry_date);

          SELECT * INTO v_current_stock FROM item_warehouse_stock
          WHERE item_id = p_item_id AND warehouse_id = p_warehouse_id
          FOR UPDATE;

          IF NOT FOUND THEN
            INSERT INTO item_warehouse_stock
              (item_id, warehouse_id, qty_on_hand, avg_cost)
            VALUES (p_item_id, p_warehouse_id, p_qty, p_unit_cost);
          ELSE
            v_new_avg_cost := ROUND(
              ((v_current_stock.qty_on_hand * v_current_stock.avg_cost)
                 + (p_qty * p_unit_cost))
              / NULLIF(v_current_stock.qty_on_hand + p_qty, 0), 4);
            UPDATE item_warehouse_stock
            SET qty_on_hand = qty_on_hand + p_qty,
                avg_cost = COALESCE(v_new_avg_cost, p_unit_cost)
            WHERE item_id = p_item_id AND warehouse_id = p_warehouse_id;
          END IF;

          INSERT INTO stock_transactions
            (item_id, warehouse_id, transaction_type, qty, unit_cost,
             total_cost, reference_type, reference_id, created_by)
          VALUES
            (p_item_id, p_warehouse_id, 'RECEIPT', p_qty, p_unit_cost,
             ROUND(p_qty * p_unit_cost, 2), p_reference_type,
             p_reference_id, fn_current_user_id())
          RETURNING id INTO v_txn_id;

          RETURN jsonb_build_object('success', TRUE, 'transaction_id',
            v_txn_id, 'qty', p_qty, 'unit_cost', p_unit_cost);
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC: fn_issue_stock
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_issue_stock(
          p_item_id UUID, p_warehouse_id UUID, p_qty NUMERIC,
          p_reference_type VARCHAR, p_reference_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_item          items%ROWTYPE;
          v_available     NUMERIC(18,4);
          v_remaining_qty NUMERIC(18,4) := p_qty;
          v_lot           RECORD;
          v_take          NUMERIC(18,4);
          v_total_cost    NUMERIC(18,2) := 0;
          v_weighted_cost NUMERIC(18,4);
          v_txn_id        UUID;
        BEGIN
          IF p_qty <= 0 THEN
            PERFORM fn_raise_error('INVALID_QTY',
              'Qty pengeluaran harus lebih dari 0.');
          END IF;

          SELECT * INTO v_item FROM items
          WHERE id = p_item_id AND is_active = TRUE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('ITEM_NOT_FOUND',
              'Item tidak ditemukan atau nonaktif.');
          END IF;

          IF fn_current_entity_id() IS DISTINCT FROM v_item.entity_id THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'Stock moves must stay within your own entity.');
          END IF;

          -- Anti-negative: check the aggregate before burning lots.
          SELECT qty_on_hand INTO v_available FROM item_warehouse_stock
          WHERE item_id = p_item_id AND warehouse_id = p_warehouse_id
          FOR UPDATE;
          IF v_available IS NULL OR v_available < p_qty THEN
            PERFORM fn_raise_error('INSUFFICIENT_STOCK',
              format('Stok tidak cukup: tersedia %s, diminta %s.',
                     COALESCE(v_available, 0), p_qty));
          END IF;

          IF v_item.costing_method = 'MOVING_AVERAGE' THEN
            SELECT avg_cost INTO v_weighted_cost FROM item_warehouse_stock
            WHERE item_id = p_item_id AND warehouse_id = p_warehouse_id;
            v_total_cost := ROUND(p_qty * v_weighted_cost, 2);
          ELSE
            -- FIFO / FEFO: burn lot layers, oldest (or nearest-expiry)
            -- first. Expired lots are skipped entirely.
            FOR v_lot IN
              SELECT * FROM stock_lots
              WHERE item_id = p_item_id
                AND warehouse_id = p_warehouse_id
                AND qty_remaining > 0
                AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
              ORDER BY
                CASE WHEN v_item.requires_fefo THEN expiry_date END
                  ASC NULLS LAST,
                received_date ASC
              FOR UPDATE
            LOOP
              EXIT WHEN v_remaining_qty <= 0;
              v_take := LEAST(v_lot.qty_remaining, v_remaining_qty);
              UPDATE stock_lots
              SET qty_remaining = qty_remaining - v_take
              WHERE id = v_lot.id;
              v_total_cost := v_total_cost
                + ROUND(v_take * v_lot.unit_cost, 2);
              v_remaining_qty := v_remaining_qty - v_take;
            END LOOP;

            IF v_remaining_qty > 0 THEN
              PERFORM fn_raise_error('LOT_STOCK_DRIFT',
                'Saldo agregat tidak sinkron dengan lot fisik yang '
                'valid (kemungkinan lot kadaluarsa). Perlu stock opname.');
            END IF;
            v_weighted_cost := ROUND(v_total_cost / p_qty, 4);
          END IF;

          UPDATE item_warehouse_stock
          SET qty_on_hand = qty_on_hand - p_qty
          WHERE item_id = p_item_id AND warehouse_id = p_warehouse_id;

          INSERT INTO stock_transactions
            (item_id, warehouse_id, transaction_type, qty, unit_cost,
             total_cost, reference_type, reference_id, created_by)
          VALUES
            (p_item_id, p_warehouse_id, 'ISSUE', -p_qty, v_weighted_cost,
             v_total_cost, p_reference_type, p_reference_id,
             fn_current_user_id())
          RETURNING id INTO v_txn_id;

          RETURN jsonb_build_object('success', TRUE, 'transaction_id',
            v_txn_id, 'qty', p_qty, 'total_cost', v_total_cost,
            'weighted_unit_cost', v_weighted_cost);
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC: fn_transfer_stock
    # ------------------------------------------------------------------
    opExecute = op.execute
    opExecute(
        """
        CREATE OR REPLACE FUNCTION fn_transfer_stock(
          p_item_id UUID, p_from_warehouse_id UUID,
          p_to_warehouse_id UUID, p_qty NUMERIC
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_from_entity UUID;
          v_to_entity   UUID;
          v_issue_result JSONB;
        BEGIN
          IF fn_current_role() NOT IN
             ('WAREHOUSE_OPERATOR','DEPT_HEAD_WAREHOUSE','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only warehouse roles can transfer stock.');
          END IF;

          SELECT entity_id INTO v_from_entity FROM warehouses
          WHERE id = p_from_warehouse_id;
          SELECT entity_id INTO v_to_entity FROM warehouses
          WHERE id = p_to_warehouse_id;
          IF v_from_entity IS DISTINCT FROM v_to_entity THEN
            PERFORM fn_raise_error('CROSS_ENTITY_TRANSFER',
              'Transfer lintas entity harus lewat modul Intercompany.');
          END IF;
          IF v_from_entity IS DISTINCT FROM fn_current_entity_id() THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only transfer within your own entity.');
          END IF;

          v_issue_result := fn_issue_stock(p_item_id, p_from_warehouse_id,
            p_qty, 'TRANSFER', NULL);
          PERFORM fn_receive_stock(p_item_id, p_to_warehouse_id, p_qty,
            (v_issue_result->>'weighted_unit_cost')::numeric,
            'TRANSFER', NULL, NULL);

          RETURN jsonb_build_object('success', TRUE,
            'qty_transferred', p_qty,
            'unit_cost', v_issue_result->>'weighted_unit_cost');
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC: fn_complete_work_order
    # ------------------------------------------------------------------
    opExecute(
        """
        CREATE OR REPLACE FUNCTION fn_complete_work_order(
          p_work_order_id UUID, p_qty_produced NUMERIC
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_wo             work_orders%ROWTYPE;
          v_bom            boms%ROWTYPE;
          v_component      RECORD;
          v_qty_needed     NUMERIC(18,4);
          v_material_cost  NUMERIC(18,2) := 0;
          v_component_cost JSONB;
          v_material_by_account JSONB := '{}'::jsonb;
          v_account_key    TEXT;
          v_foh_rate       NUMERIC(18,4);
          v_foh_allocated  NUMERIC(18,2);
          v_cogm           NUMERIC(18,2);
          v_unit_cost      NUMERIC(18,4);
          v_finished_item  items%ROWTYPE;
          v_je_lines       JSONB := '[]'::jsonb;
          v_je_result      JSONB;
        BEGIN
          IF fn_current_role() NOT IN
             ('DEPT_HEAD_WAREHOUSE','FINANCE_OPERATOR','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only warehouse heads / finance can complete work orders.');
          END IF;

          SELECT * INTO v_wo FROM work_orders
          WHERE id = p_work_order_id FOR UPDATE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('WO_NOT_FOUND',
              'Work order tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_wo.entity_id THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only complete work orders of your own entity.');
          END IF;
          IF v_wo.status NOT IN ('DRAFT','IN_PROGRESS') THEN
            PERFORM fn_raise_error('WO_INVALID_STATUS',
              format('Work order berstatus %s, tidak bisa di-complete.',
                     v_wo.status));
          END IF;
          IF p_qty_produced <= 0 THEN
            PERFORM fn_raise_error('INVALID_QTY',
              'Qty produksi harus lebih dari 0.');
          END IF;

          SELECT * INTO v_bom FROM boms WHERE id = v_wo.bom_id;
          SELECT * INTO v_finished_item FROM items WHERE id = v_wo.item_id;
          IF v_finished_item.gl_inventory_account_id IS NULL THEN
            PERFORM fn_raise_error('FG_ACCOUNT_MISSING',
              'Item hasil produksi belum punya gl_inventory_account_id.');
          END IF;

          -- Consume each BOM component, prorated by actual production
          -- vs recipe yield, plus waste allowance.
          FOR v_component IN
            SELECT * FROM bom_components
            WHERE bom_id = v_bom.id
            ORDER BY sequence_no
          LOOP
            v_qty_needed := v_component.qty_per_yield
              * (p_qty_produced / v_bom.yield_qty)
              * (1 + v_component.waste_pct / 100);
            v_component_cost := fn_issue_stock(
              v_component.component_item_id, v_wo.warehouse_id,
              v_qty_needed, 'WORK_ORDER', p_work_order_id);
            v_material_cost := v_material_cost
              + (v_component_cost->>'total_cost')::numeric;

            v_account_key := (SELECT gl_inventory_account_id FROM items
              WHERE id = v_component.component_item_id)::text;
            IF v_account_key IS NULL THEN
              PERFORM fn_raise_error('MATERIAL_ACCOUNT_MISSING',
                format('Item %s belum punya gl_inventory_account_id.',
                       v_component.component_item_id));
            END IF;
            v_material_by_account := jsonb_set(v_material_by_account,
              ARRAY[v_account_key],
              to_jsonb(COALESCE(
                (v_material_by_account->>v_account_key)::numeric, 0)
                + (v_component_cost->>'total_cost')::numeric));
          END LOOP;

          -- FOH allocation: rate x driver qty used on this WO.
          IF v_wo.cost_center_id IS NOT NULL THEN
            SELECT total_estimated_overhead
              / NULLIF(total_capacity_driver, 0)
            INTO v_foh_rate
            FROM cost_centers WHERE id = v_wo.cost_center_id;
            IF v_foh_rate IS NULL THEN
              PERFORM fn_raise_error('FOH_RATE_UNDEFINED',
                'Total kapasitas cost driver = 0, tarif FOH tidak '
                'dapat dihitung.');
            END IF;
            v_foh_allocated := ROUND(v_foh_rate * v_wo.driver_qty_used, 2);
          ELSE
            v_foh_allocated := 0;
          END IF;

          -- COGM = materials + direct labor + allocated FOH.
          v_cogm := v_material_cost + v_wo.direct_labor_cost
            + v_foh_allocated;
          v_unit_cost := ROUND(v_cogm / p_qty_produced, 4);

          PERFORM fn_receive_stock(v_wo.item_id, v_wo.warehouse_id,
            p_qty_produced, v_unit_cost, 'WORK_ORDER', p_work_order_id,
            NULL);

          -- GL: Dr FG Inventory (COGM) | Cr per-account materials,
          -- Cr Accrued Labor, Cr FOH Applied.
          v_je_lines := jsonb_build_array(
            jsonb_build_object('account_id',
              v_finished_item.gl_inventory_account_id,
              'debit_amount', v_cogm, 'credit_amount', 0));
          FOR v_account_key IN SELECT jsonb_object_keys(v_material_by_account)
          LOOP
            v_je_lines := v_je_lines || jsonb_build_object(
              'account_id', v_account_key::uuid,
              'debit_amount', 0,
              'credit_amount',
              (v_material_by_account->>v_account_key)::numeric);
          END LOOP;
          IF v_wo.direct_labor_cost > 0 THEN
            IF v_wo.gl_accrued_labor_account_id IS NULL THEN
              PERFORM fn_raise_error('LABOR_ACCOUNT_MISSING',
                'direct_labor_cost > 0 tapi akun accrued labor belum '
                'diisi pada work order.');
            END IF;
            v_je_lines := v_je_lines || jsonb_build_object(
              'account_id', v_wo.gl_accrued_labor_account_id,
              'debit_amount', 0, 'credit_amount', v_wo.direct_labor_cost);
          END IF;
          IF v_foh_allocated > 0 THEN
            IF (SELECT gl_foh_applied_account_id FROM cost_centers
                WHERE id = v_wo.cost_center_id) IS NULL THEN
              PERFORM fn_raise_error('FOH_ACCOUNT_MISSING',
                'FOH dialokasikan tapi akun FOH Applied belum diisi '
                'pada cost center.');
            END IF;
            v_je_lines := v_je_lines || jsonb_build_object(
              'account_id',
              (SELECT gl_foh_applied_account_id FROM cost_centers
               WHERE id = v_wo.cost_center_id),
              'debit_amount', 0, 'credit_amount', v_foh_allocated);
          END IF;

          v_je_result := fn_create_journal_entry(
            v_wo.entity_id, CURRENT_DATE,
            format('WO Completion %s — COGM', v_wo.wo_number),
            'IDR', v_je_lines);
          PERFORM fn_post_journal_entry(
            (v_je_result->>'journal_entry_id')::uuid);

          UPDATE work_orders
          SET status = 'COMPLETED', qty_produced = p_qty_produced,
              journal_entry_id = (v_je_result->>'journal_entry_id')::uuid,
              completed_at = now()
          WHERE id = p_work_order_id;

          INSERT INTO system_logs
            (actor_id, entity_id, action, table_name, record_id, after_data)
          VALUES (fn_current_user_id(), v_wo.entity_id, 'COMPLETE',
            'work_orders', p_work_order_id::text,
            jsonb_build_object('cogm', v_cogm, 'unit_cost', v_unit_cost));

          RETURN jsonb_build_object('success', TRUE,
            'work_order_id', p_work_order_id,
            'cogm', v_cogm, 'unit_cost', v_unit_cost,
            'material_cost', v_material_cost,
            'foh_allocated', v_foh_allocated);
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS fn_complete_work_order(UUID, NUMERIC)")
    op.execute("DROP FUNCTION IF EXISTS fn_transfer_stock(UUID, UUID, UUID, NUMERIC)")
    op.execute("DROP FUNCTION IF EXISTS fn_issue_stock(UUID, UUID, NUMERIC, VARCHAR, UUID)")
    op.execute("DROP FUNCTION IF EXISTS fn_receive_stock(UUID, UUID, NUMERIC, NUMERIC, VARCHAR, UUID, DATE)")
    op.execute("DROP TABLE IF EXISTS work_orders CASCADE")
    op.execute("DROP TABLE IF EXISTS cost_centers CASCADE")
    op.execute("DROP TABLE IF EXISTS bom_components CASCADE")
    op.execute("DROP TABLE IF EXISTS boms CASCADE")
    op.execute("DROP TABLE IF EXISTS stock_transactions CASCADE")
    op.execute("DROP TABLE IF EXISTS item_warehouse_stock CASCADE")
    op.execute("DROP TABLE IF EXISTS stock_lots CASCADE")
    op.execute("DROP TABLE IF EXISTS items CASCADE")
    op.execute("DROP TABLE IF EXISTS warehouses CASCADE")
    op.execute("DROP TYPE IF EXISTS bom_type_enum")
    op.execute("DROP TYPE IF EXISTS wo_status_enum")
    op.execute("DROP TYPE IF EXISTS stock_txn_type_enum")
    op.execute("DROP TYPE IF EXISTS costing_method_enum")
    op.execute("DROP TYPE IF EXISTS item_type_enum")
