"""Add Modul 7: Fixed Asset Management

Revision ID: b9d4f2a8c61e
Revises: a7c2e9f41d08
Create Date: 2026-08-31

Tables: fixed_assets, asset_depreciation_schedule, asset_disposals.
RPCs: fn_register_fixed_asset, fn_run_monthly_depreciation_batch,
      fn_dispose_fixed_asset (appended in part 2).

Dispose RPC uses the NULL-hardened role check
(fn_current_role() IS NULL OR fn_current_role() NOT IN ...)
closing the NULL-bypass latent bug found in Modul 6 testing.
"""

from alembic import op

revision = "b9d4f2a8c61e"
down_revision = "a7c2e9f41d08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enums
    # ------------------------------------------------------------------
    op.execute(
        "CREATE TYPE asset_category_enum AS ENUM "
        "('TANGIBLE','INTANGIBLE')"
    )
    op.execute(
        "CREATE TYPE depreciation_method_enum AS ENUM "
        "('STRAIGHT_LINE','DECLINING_BALANCE')"
    )
    op.execute(
        "CREATE TYPE asset_status_enum AS ENUM "
        "('ACTIVE','FULLY_DEPRECIATED','DISPOSED')"
    )
    op.execute(
        "CREATE TYPE disposal_type_enum AS ENUM "
        "('SALE','WRITE_OFF','DONATION')"
    )

    # ------------------------------------------------------------------
    # entity_gl_defaults: default depreciation expense account
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE entity_gl_defaults ADD COLUMN "
        "gl_depr_expense_default_account_id UUID "
        "REFERENCES chart_of_accounts(id)"
    )

    # ------------------------------------------------------------------
    # fixed_assets
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE fixed_assets (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          asset_code VARCHAR(30) NOT NULL,
          asset_name VARCHAR(150) NOT NULL,
          asset_category asset_category_enum NOT NULL,
          department_code VARCHAR(30),
          acquisition_date DATE NOT NULL,
          acquisition_cost NUMERIC(18,2) NOT NULL
            CHECK (acquisition_cost > 0),
          salvage_value NUMERIC(18,2) NOT NULL DEFAULT 0
            CHECK (salvage_value >= 0),
          useful_life_months SMALLINT NOT NULL
            CHECK (useful_life_months > 0),
          depreciation_method depreciation_method_enum NOT NULL
            DEFAULT 'STRAIGHT_LINE',
          declining_rate_pct NUMERIC(6,4),
          accumulated_depreciation NUMERIC(18,2)
            NOT NULL DEFAULT 0,
          book_value NUMERIC(18,2) NOT NULL,
          status asset_status_enum NOT NULL DEFAULT 'ACTIVE',
          gl_asset_account_id UUID NOT NULL
            REFERENCES chart_of_accounts(id),
          gl_accum_depr_account_id UUID NOT NULL
            REFERENCES chart_of_accounts(id),
          gl_depr_expense_account_id UUID
            REFERENCES chart_of_accounts(id),
          acquisition_journal_entry_id UUID
            REFERENCES journal_entries(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entity_id, asset_code),
          CONSTRAINT chk_declining_rate CHECK (
            (depreciation_method = 'DECLINING_BALANCE'
             AND declining_rate_pct IS NOT NULL)
            OR (depreciation_method = 'STRAIGHT_LINE')
          )
        )
        """
    )

    # ------------------------------------------------------------------
    # asset_depreciation_schedule (immutable history)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE asset_depreciation_schedule (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          asset_id UUID NOT NULL REFERENCES fixed_assets(id),
          period_year SMALLINT NOT NULL,
          period_month SMALLINT NOT NULL
            CHECK (period_month BETWEEN 1 AND 12),
          depreciation_amount NUMERIC(18,2) NOT NULL,
          accumulated_after NUMERIC(18,2) NOT NULL,
          book_value_after NUMERIC(18,2) NOT NULL,
          journal_entry_id UUID REFERENCES journal_entries(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (asset_id, period_year, period_month)
        )
        """
    )

    # ------------------------------------------------------------------
    # asset_disposals
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE asset_disposals (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          asset_id UUID NOT NULL REFERENCES fixed_assets(id),
          disposal_date DATE NOT NULL,
          disposal_type disposal_type_enum NOT NULL,
          disposal_proceeds NUMERIC(18,2) NOT NULL DEFAULT 0,
          book_value_at_disposal NUMERIC(18,2) NOT NULL,
          gain_loss_amount NUMERIC(18,2) NOT NULL,
          journal_entry_id UUID REFERENCES journal_entries(id),
          created_by UUID NOT NULL REFERENCES user_profiles(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # ------------------------------------------------------------------
    # RLS + revoke (mutations only via SECURITY DEFINER RPCs)
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE fixed_assets ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY fa_select_scoped ON fixed_assets
        FOR SELECT USING (
          entity_id = fn_current_entity_id()
          OR fn_current_role() IN ('SUPER_ADMIN','IT_ADMIN')
        )
        """
    )
    op.execute(
        "REVOKE ALL ON fixed_assets FROM PUBLIC"
    )

    op.execute(
        "ALTER TABLE asset_depreciation_schedule "
        "ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY ads_select_scoped
        ON asset_depreciation_schedule FOR SELECT USING (
          EXISTS (
            SELECT 1 FROM fixed_assets fa
            WHERE fa.id = asset_depreciation_schedule.asset_id
              AND (fa.entity_id = fn_current_entity_id()
                   OR fn_current_role()
                      IN ('SUPER_ADMIN','IT_ADMIN'))
          )
        )
        """
    )
    op.execute(
        "REVOKE ALL ON asset_depreciation_schedule FROM PUBLIC"
    )

    op.execute(
        "ALTER TABLE asset_disposals ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY ad_select_scoped ON asset_disposals
        FOR SELECT USING (
          EXISTS (
            SELECT 1 FROM fixed_assets fa
            WHERE fa.id = asset_disposals.asset_id
              AND (fa.entity_id = fn_current_entity_id()
                   OR fn_current_role()
                      IN ('SUPER_ADMIN','IT_ADMIN'))
          )
        )
        """
    )
    op.execute("REVOKE ALL ON asset_disposals FROM PUBLIC")


    # ------------------------------------------------------------------
    # RPC 1: fn_register_fixed_asset
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_register_fixed_asset(
          p_entity_id UUID, p_asset_name VARCHAR,
          p_asset_category asset_category_enum,
          p_acquisition_date DATE, p_acquisition_cost NUMERIC,
          p_salvage_value NUMERIC, p_useful_life_months SMALLINT,
          p_depreciation_method depreciation_method_enum,
          p_declining_rate_pct NUMERIC,
          p_gl_asset_account_id UUID,
          p_gl_accum_depr_account_id UUID,
          p_funding_account_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_asset_id UUID;
          v_asset_code VARCHAR(30);
          v_je_result JSONB;
        BEGIN
          IF fn_current_role() IS NULL OR fn_current_role()
             NOT IN ('FINANCE_OPERATOR','DEPT_HEAD_FA',
                     'SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only finance staff can register assets.');
          END IF;

          IF p_salvage_value >= p_acquisition_cost THEN
            PERFORM fn_raise_error('INVALID_SALVAGE_VALUE',
              'Salvage value must be smaller than '
              'acquisition cost.');
          END IF;

          v_asset_code := 'FA-' ||
            to_char(p_acquisition_date, 'YYYY') || '-' ||
            upper(substr(md5(random()::text), 1, 6));

          INSERT INTO fixed_assets (
            entity_id, asset_code, asset_name,
            asset_category, acquisition_date,
            acquisition_cost, salvage_value,
            useful_life_months, depreciation_method,
            declining_rate_pct, book_value,
            gl_asset_account_id, gl_accum_depr_account_id
          ) VALUES (
            p_entity_id, v_asset_code, p_asset_name,
            p_asset_category, p_acquisition_date,
            p_acquisition_cost, p_salvage_value,
            p_useful_life_months, p_depreciation_method,
            p_declining_rate_pct, p_acquisition_cost,
            p_gl_asset_account_id, p_gl_accum_depr_account_id
          ) RETURNING id INTO v_asset_id;

          v_je_result := fn_create_journal_entry(
            p_entity_id, p_acquisition_date,
            format('Fixed Asset Acquisition: %s',
                   p_asset_name), 'IDR',
            jsonb_build_array(
              jsonb_build_object('account_id',
                p_gl_asset_account_id,
                'debit_amount', p_acquisition_cost,
                'credit_amount', 0),
              jsonb_build_object('account_id',
                p_funding_account_id,
                'debit_amount', 0,
                'credit_amount', p_acquisition_cost)
            ));

          PERFORM fn_post_journal_entry(
            (v_je_result->>'journal_entry_id')::uuid);

          UPDATE fixed_assets
            SET acquisition_journal_entry_id =
                (v_je_result->>'journal_entry_id')::uuid
            WHERE id = v_asset_id;

          RETURN jsonb_build_object(
            'asset_id', v_asset_id,
            'asset_code', v_asset_code,
            'journal_entry_id',
            v_je_result->>'journal_entry_id');
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 2: fn_run_monthly_depreciation_batch
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION
        fn_run_monthly_depreciation_batch(
          p_entity_id UUID, p_period_year SMALLINT,
          p_period_month SMALLINT
        ) RETURNS JSONB LANGUAGE plpgsql
        SECURITY DEFINER AS $$
        DECLARE
          v_asset RECORD;
          v_depr_amount NUMERIC(18,2);
          v_max_depr NUMERIC(18,2);
          v_je_lines JSONB := '[]'::jsonb;
          v_total_depr NUMERIC(18,2) := 0;
          v_expense_account UUID;
          v_je_result JSONB;
          v_asset_count INT := 0;
        BEGIN
          IF fn_current_role() IS NULL OR fn_current_role()
             NOT IN ('FINANCE_OPERATOR','DEPT_HEAD_FA',
                     'SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only finance staff can run depreciation.');
          END IF;

          IF EXISTS (
            SELECT 1 FROM asset_depreciation_schedule ads
            JOIN fixed_assets fa ON fa.id = ads.asset_id
            WHERE fa.entity_id = p_entity_id
              AND ads.period_year = p_period_year
              AND ads.period_month = p_period_month
          ) THEN
            PERFORM fn_raise_error('PERIOD_ALREADY_PROCESSED',
              'Depreciation for this entity and period '
              'has already been run.');
          END IF;

          FOR v_asset IN
            SELECT * FROM fixed_assets
            WHERE entity_id = p_entity_id
              AND status = 'ACTIVE'
            FOR UPDATE
          LOOP
            v_max_depr := v_asset.acquisition_cost
              - v_asset.salvage_value
              - v_asset.accumulated_depreciation;
            IF v_max_depr <= 0 THEN
              UPDATE fixed_assets
                SET status = 'FULLY_DEPRECIATED'
                WHERE id = v_asset.id;
              CONTINUE;
            END IF;

            IF v_asset.depreciation_method
               = 'STRAIGHT_LINE' THEN
              v_depr_amount := ROUND(
                (v_asset.acquisition_cost
                 - v_asset.salvage_value)
                / v_asset.useful_life_months, 2);
            ELSE
              v_depr_amount := ROUND(
                v_asset.book_value
                * (v_asset.declining_rate_pct / 12 / 100),
                2);
            END IF;
            v_depr_amount := LEAST(v_depr_amount,
                                    v_max_depr);

            INSERT INTO asset_depreciation_schedule (
              asset_id, period_year, period_month,
              depreciation_amount, accumulated_after,
              book_value_after
            ) VALUES (
              v_asset.id, p_period_year, p_period_month,
              v_depr_amount,
              v_asset.accumulated_depreciation
                + v_depr_amount,
              v_asset.book_value - v_depr_amount
            );

            UPDATE fixed_assets SET
              accumulated_depreciation =
                accumulated_depreciation + v_depr_amount,
              book_value = book_value - v_depr_amount,
              status = (CASE
                WHEN book_value - v_depr_amount
                     <= salvage_value
                THEN 'FULLY_DEPRECIATED'
                ELSE 'ACTIVE' END)::asset_status_enum
            WHERE id = v_asset.id;

            v_expense_account := COALESCE(
              v_asset.gl_depr_expense_account_id,
              (SELECT gl_depr_expense_default_account_id
               FROM entity_gl_defaults
               WHERE entity_id = p_entity_id));

            IF v_expense_account IS NULL THEN
              PERFORM fn_raise_error(
                'ACCOUNT_NOT_POSTABLE',
                'No depreciation expense account '
                'configured for this asset.');
            END IF;

            v_je_lines := v_je_lines ||
              jsonb_build_object('account_id',
                v_expense_account,
                'debit_amount', v_depr_amount,
                'credit_amount', 0) ||
              jsonb_build_object('account_id',
                v_asset.gl_accum_depr_account_id,
                'debit_amount', 0,
                'credit_amount', v_depr_amount);
            v_total_depr := v_total_depr + v_depr_amount;
            v_asset_count := v_asset_count + 1;
          END LOOP;

          IF v_asset_count = 0 THEN
            RETURN jsonb_build_object(
              'asset_count', 0, 'total_depreciation', 0,
              'note', 'No active assets to depreciate.');
          END IF;

          v_je_result := fn_create_journal_entry(
            p_entity_id,
            (make_date(p_period_year, p_period_month, 1)
             + INTERVAL '1 month - 1 day')::date,
            format('Monthly Depreciation %s-%s (%s aset)',
                   p_period_month, p_period_year,
                   v_asset_count),
            'IDR', v_je_lines);
          PERFORM fn_post_journal_entry(
            (v_je_result->>'journal_entry_id')::uuid);

          UPDATE asset_depreciation_schedule
            SET journal_entry_id =
                (v_je_result->>'journal_entry_id')::uuid
            WHERE asset_id IN (
              SELECT id FROM fixed_assets
              WHERE entity_id = p_entity_id
            )
            AND period_year = p_period_year
            AND period_month = p_period_month;

          RETURN jsonb_build_object(
            'asset_count', v_asset_count,
            'total_depreciation', v_total_depr,
            'journal_entry_id',
            v_je_result->>'journal_entry_id');
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC 3: fn_dispose_fixed_asset
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_dispose_fixed_asset(
          p_asset_id UUID, p_disposal_date DATE,
          p_disposal_type disposal_type_enum,
          p_disposal_proceeds NUMERIC,
          p_proceeds_account_id UUID,
          p_gain_loss_account_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql
        SECURITY DEFINER AS $$
        DECLARE
          v_asset fixed_assets%ROWTYPE;
          v_gain_loss NUMERIC(18,2);
          v_je_lines JSONB;
          v_je_result JSONB;
          v_disposal_id UUID;
        BEGIN
          IF fn_current_role() IS NULL OR fn_current_role()
             NOT IN ('DEPT_HEAD_FA','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN',
              'Only Head of F&A or Super Admin can '
              'dispose assets.');
          END IF;

          SELECT * INTO v_asset FROM fixed_assets
            WHERE id = p_asset_id FOR UPDATE;
          IF v_asset.status = 'DISPOSED' THEN
            PERFORM fn_raise_error('ASSET_ALREADY_DISPOSED',
              'Asset already disposed.');
          END IF;

          v_gain_loss := p_disposal_proceeds
            - v_asset.book_value;

          v_je_lines := jsonb_build_array(
            jsonb_build_object('account_id',
              v_asset.gl_accum_depr_account_id,
              'debit_amount',
              v_asset.accumulated_depreciation,
              'credit_amount', 0),
            jsonb_build_object('account_id',
              v_asset.gl_asset_account_id,
              'debit_amount', 0,
              'credit_amount', v_asset.acquisition_cost)
          );
          IF p_disposal_proceeds > 0 THEN
            v_je_lines := v_je_lines ||
              jsonb_build_object('account_id',
                p_proceeds_account_id,
                'debit_amount', p_disposal_proceeds,
                'credit_amount', 0);
          END IF;
          IF v_gain_loss > 0 THEN
            v_je_lines := v_je_lines ||
              jsonb_build_object('account_id',
                p_gain_loss_account_id,
                'debit_amount', 0,
                'credit_amount', v_gain_loss);
          ELSIF v_gain_loss < 0 THEN
            v_je_lines := v_je_lines ||
              jsonb_build_object('account_id',
                p_gain_loss_account_id,
                'debit_amount', -v_gain_loss,
                'credit_amount', 0);
          END IF;

          v_je_result := fn_create_journal_entry(
            v_asset.entity_id, p_disposal_date,
            format('Asset Disposal: %s (%s)',
                   v_asset.asset_name, p_disposal_type),
            'IDR', v_je_lines);
          PERFORM fn_post_journal_entry(
            (v_je_result->>'journal_entry_id')::uuid);

          INSERT INTO asset_disposals (
            asset_id, disposal_date, disposal_type,
            disposal_proceeds, book_value_at_disposal,
            gain_loss_amount, journal_entry_id, created_by
          ) VALUES (
            p_asset_id, p_disposal_date, p_disposal_type,
            p_disposal_proceeds, v_asset.book_value,
            v_gain_loss,
            (v_je_result->>'journal_entry_id')::uuid,
            fn_current_user_id()
          ) RETURNING id INTO v_disposal_id;

          UPDATE fixed_assets SET status = 'DISPOSED'
            WHERE id = p_asset_id;

          RETURN jsonb_build_object(
            'disposal_id', v_disposal_id,
            'gain_loss', v_gain_loss,
            'journal_entry_id',
            v_je_result->>'journal_entry_id');
        END;
        $$;
        """
    )



def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS asset_disposals")
    op.execute("DROP TABLE IF EXISTS asset_depreciation_schedule")
    op.execute("DROP TABLE IF EXISTS fixed_assets")
    op.execute(
        "ALTER TABLE entity_gl_defaults DROP COLUMN "
        "IF EXISTS gl_depr_expense_default_account_id"
    )
    op.execute("DROP TYPE IF EXISTS disposal_type_enum")
    op.execute("DROP TYPE IF EXISTS asset_status_enum")
    op.execute("DROP TYPE IF EXISTS depreciation_method_enum")
    op.execute("DROP TYPE IF EXISTS asset_category_enum")
