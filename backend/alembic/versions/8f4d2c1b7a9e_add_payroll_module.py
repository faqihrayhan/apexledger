"""Add Modul 2: HR Finance, Payroll & Tax

Revision ID: 8f4d2c1b7a9e
Revises: 711149b12a06
Create Date: 2026-08-30

Tables (11): employees, company_calendar, attendance_records,
payroll_component_master, bpjs_rate_config, tax_pph21_ter_table,
ptkp_ter_category_map, overtime_multiplier_config, payroll_periods,
payroll_entries, payroll_entry_lines.

RPCs (3): fn_calculate_payroll_entry, fn_approve_payroll_period,
fn_disburse_payroll_period — all auto-posting to the Modul 1 GL engine.

Seeds (config-driven, not hardcoded in RPC):
- payroll_component_master (9 components)
- bpjs_rate_config (Kesehatan/JHT/JP employee+employer rates, caps)
- tax_pph21_ter_table (full official PMK 168/2023 table, 126 brackets)
- ptkp_ter_category_map (PTKP status -> TER category A/B/C)

Source for tax data: Lampiran PMK 168/PMK.03/2023 (TER bulanan),
effective 2024-01-01. Bracket semantics follow the official table:
"di atas X s.d. Y" -> income > income_from AND income <= income_to.
"""

from alembic import op

revision = "8f4d2c1b7a9e"
down_revision = "711149b12a06"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Official TER table (PMK 168/PMK.03/2023) — (income_from, income_to, rate_pct)
# income_from is EXCLUSIVE ("di atas"), income_to INCLUSIVE ("s.d.");
# income_to NULL = top bracket (no upper bound).
# ---------------------------------------------------------------------------
TER_A = [
    (-1, 5_400_000, 0.0),
    (5_400_000, 5_650_000, 0.25),
    (5_650_000, 5_950_000, 0.50),
    (5_950_000, 6_300_000, 0.75),
    (6_300_000, 6_750_000, 1.0),
    (6_750_000, 7_500_000, 1.25),
    (7_500_000, 8_550_000, 1.50),
    (8_550_000, 9_650_000, 1.75),
    (9_650_000, 10_050_000, 2.0),
    (10_050_000, 10_350_000, 2.25),
    (10_350_000, 10_700_000, 2.50),
    (10_700_000, 11_050_000, 3.0),
    (11_050_000, 11_600_000, 3.50),
    (11_600_000, 12_500_000, 4.0),
    (12_500_000, 13_750_000, 5.0),
    (13_750_000, 15_100_000, 6.0),
    (15_100_000, 16_950_000, 7.0),
    (16_950_000, 19_750_000, 8.0),
    (19_750_000, 24_150_000, 9.0),
    (24_150_000, 26_450_000, 10.0),
    (26_450_000, 28_000_000, 11.0),
    (28_000_000, 30_050_000, 12.0),
    (30_050_000, 32_400_000, 13.0),
    (32_400_000, 35_400_000, 14.0),
    (35_400_000, 39_100_000, 15.0),
    (39_100_000, 43_850_000, 16.0),
    (43_850_000, 47_800_000, 17.0),
    (47_800_000, 51_400_000, 18.0),
    (51_400_000, 56_300_000, 19.0),
    (56_300_000, 62_200_000, 20.0),
    (62_200_000, 68_600_000, 21.0),
    (68_600_000, 77_500_000, 22.0),
    (77_500_000, 89_000_000, 23.0),
    (89_000_000, 103_000_000, 24.0),
    (103_000_000, 125_000_000, 25.0),
    (125_000_000, 157_000_000, 26.0),
    (157_000_000, 206_000_000, 27.0),
    (206_000_000, 337_000_000, 28.0),
    (337_000_000, 454_000_000, 29.0),
    (454_000_000, 550_000_000, 30.0),
    (550_000_000, 695_000_000, 31.0),
    (695_000_000, 910_000_000, 32.0),
    (910_000_000, 1_400_000_000, 33.0),
    (1_400_000_000, None, 34.0),
]

TER_B = [
    (-1, 6_200_000, 0.0),
    (6_200_000, 6_500_000, 0.25),
    (6_500_000, 6_850_000, 0.50),
    (6_850_000, 7_300_000, 0.75),
    (7_300_000, 9_200_000, 1.0),
    (9_200_000, 10_750_000, 1.50),
    (10_750_000, 11_250_000, 2.0),
    (11_250_000, 11_600_000, 2.50),
    (11_600_000, 12_600_000, 3.0),
    (12_600_000, 13_600_000, 4.0),
    (13_600_000, 14_950_000, 5.0),
    (14_950_000, 16_400_000, 6.0),
    (16_400_000, 18_450_000, 7.0),
    (18_450_000, 21_850_000, 8.0),
    (21_850_000, 26_000_000, 9.0),
    (26_000_000, 27_700_000, 10.0),
    (27_700_000, 29_350_000, 11.0),
    (29_350_000, 31_450_000, 12.0),
    (31_450_000, 33_950_000, 13.0),
    (33_950_000, 37_100_000, 14.0),
    (37_100_000, 41_100_000, 15.0),
    (41_100_000, 45_800_000, 16.0),
    (45_800_000, 49_500_000, 17.0),
    (49_500_000, 53_800_000, 18.0),
    (53_800_000, 58_500_000, 19.0),
    (58_500_000, 64_000_000, 20.0),
    (64_000_000, 71_000_000, 21.0),
    (71_000_000, 80_000_000, 22.0),
    (80_000_000, 93_000_000, 23.0),
    (93_000_000, 109_000_000, 24.0),
    (109_000_000, 129_000_000, 25.0),
    (129_000_000, 163_000_000, 26.0),
    (163_000_000, 211_000_000, 27.0),
    (211_000_000, 374_000_000, 28.0),
    (374_000_000, 459_000_000, 29.0),
    (459_000_000, 555_000_000, 30.0),
    (555_000_000, 704_000_000, 31.0),
    (704_000_000, 957_000_000, 32.0),
    (957_000_000, 1_405_000_000, 33.0),
    (1_405_000_000, None, 34.0),
]

TER_C = [
    (-1, 6_600_000, 0.0),
    (6_600_000, 6_950_000, 0.25),
    (6_950_000, 7_350_000, 0.50),
    (7_350_000, 7_800_000, 0.75),
    (7_800_000, 8_850_000, 1.0),
    (8_850_000, 9_800_000, 1.25),
    (9_800_000, 10_950_000, 1.50),
    (10_950_000, 11_200_000, 1.75),
    (11_200_000, 12_050_000, 2.0),
    (12_050_000, 12_950_000, 3.0),
    (12_950_000, 14_150_000, 4.0),
    (14_150_000, 15_550_000, 5.0),
    (15_550_000, 17_050_000, 6.0),
    (17_050_000, 19_500_000, 7.0),
    (19_500_000, 22_700_000, 8.0),
    (22_700_000, 26_600_000, 9.0),
    (26_600_000, 28_100_000, 10.0),
    (28_100_000, 30_100_000, 11.0),
    (30_100_000, 32_600_000, 12.0),
    (32_600_000, 35_400_000, 13.0),
    (35_400_000, 38_900_000, 14.0),
    (38_900_000, 43_000_000, 15.0),
    (43_000_000, 47_400_000, 16.0),
    (47_400_000, 51_200_000, 17.0),
    (51_200_000, 55_800_000, 18.0),
    (55_800_000, 60_400_000, 19.0),
    (60_400_000, 66_700_000, 20.0),
    (66_700_000, 74_500_000, 21.0),
    (74_500_000, 83_200_000, 22.0),
    (83_200_000, 95_600_000, 23.0),
    (95_600_000, 110_000_000, 24.0),
    (110_000_000, 134_000_000, 25.0),
    (134_000_000, 169_000_000, 26.0),
    (169_000_000, 221_000_000, 27.0),
    (221_000_000, 390_000_000, 28.0),
    (390_000_000, 463_000_000, 29.0),
    (463_000_000, 561_000_000, 30.0),
    (561_000_000, 709_000_000, 31.0),
    (709_000_000, 965_000_000, 32.0),
    (965_000_000, 1_419_000_000, 33.0),
    (1_419_000_000, None, 34.0),
]

PTKP_TER_MAP = [
    ("TK0", "A"), ("TK1", "A"), ("K0", "A"),
    ("TK2", "B"), ("TK3", "B"), ("K1", "B"), ("K2", "B"),
    ("K3", "C"),
]

COMPONENTS = [
    ("BASIC", "Gaji Pokok", "EARNING", True),
    ("OVERTIME", "Upah Lembur", "EARNING", True),
    ("INCENTIVE", "Insentif", "EARNING", True),
    ("BPJS_KES_EE", "BPJS Kesehatan (Pegawai)", "DEDUCTION", False),
    ("BPJS_JHT_EE", "BPJS JHT (Pegawai)", "DEDUCTION", False),
    ("BPJS_JP_EE", "BPJS Jaminan Pensiun (Pegawai)", "DEDUCTION", False),
    ("PPH21", "PPh 21 (TER)", "DEDUCTION", False),
    ("DENDA_UNPAID", "Potongan Hari Tidak Masuk", "DEDUCTION", False),
    ("DENDA_LATE", "Potongan Keterlambatan", "DEDUCTION", False),
]

# BPJS rates are config data (adjustable without code changes). Caps follow
# the published 2025 ceilings; update rows here when regulations change.
BPJS_RATES = [
    ("BPJS_KES_EE", 1.0, 4.0, 12_000_000, "2024-01-01"),
    ("BPJS_JHT_EE", 2.0, 3.7, None, "2024-01-01"),
    ("BPJS_JP_EE", 1.0, 2.0, 10_547_400, "2025-01-01"),
]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    op.execute("CREATE TYPE employment_type_enum AS ENUM ('MONTHLY','DAILY')")
    op.execute(
        "CREATE TYPE payroll_period_status_enum AS ENUM "
        "('DRAFT','CALCULATED','APPROVED','DISBURSED')"
    )
    op.execute("CREATE TYPE component_type_enum AS ENUM ('EARNING','DEDUCTION')")
    op.execute(
        "CREATE TYPE ptkp_status_enum AS ENUM "
        "('TK0','TK1','TK2','TK3','K0','K1','K2','K3')"
    )

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE employees (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          user_profile_id UUID REFERENCES user_profiles(id),
          employee_code VARCHAR(20) NOT NULL,
          full_name VARCHAR(150) NOT NULL,
          position VARCHAR(100),
          department_code VARCHAR(30),
          employment_type employment_type_enum NOT NULL DEFAULT 'MONTHLY',
          base_salary NUMERIC(18,2) NOT NULL CHECK (base_salary >= 0),
          ptkp_status ptkp_status_enum NOT NULL DEFAULT 'TK0',
          bank_account_no VARCHAR(30),
          npwp VARCHAR(20),
          hire_date DATE NOT NULL,
          termination_date DATE,
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entity_id, employee_code)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE company_calendar (
          entity_id UUID NOT NULL REFERENCES entities(id),
          calendar_date DATE NOT NULL,
          is_working_day BOOLEAN NOT NULL DEFAULT TRUE,
          note VARCHAR(100),
          PRIMARY KEY (entity_id, calendar_date)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE attendance_records (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          employee_id UUID NOT NULL REFERENCES employees(id),
          work_date DATE NOT NULL,
          status VARCHAR(20) NOT NULL CHECK
            (status IN ('PRESENT','LATE','UNPAID_LEAVE','PAID_LEAVE','SICK')),
          late_minutes INT NOT NULL DEFAULT 0,
          overtime_hours NUMERIC(5,2) NOT NULL DEFAULT 0,
          UNIQUE (employee_id, work_date)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE payroll_component_master (
          code VARCHAR(30) PRIMARY KEY,
          name VARCHAR(100) NOT NULL,
          type component_type_enum NOT NULL,
          is_taxable BOOLEAN NOT NULL DEFAULT TRUE,
          gl_account_id UUID REFERENCES chart_of_accounts(id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE bpjs_rate_config (
          component_code VARCHAR(30) PRIMARY KEY
            REFERENCES payroll_component_master(code),
          employee_rate_pct NUMERIC(6,4) NOT NULL,
          employer_rate_pct NUMERIC(6,4) NOT NULL,
          salary_cap NUMERIC(18,2),
          effective_date DATE NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE tax_pph21_ter_table (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          ter_category VARCHAR(2) NOT NULL CHECK
            (ter_category IN ('A','B','C')),
          income_from NUMERIC(18,2) NOT NULL,
          income_to NUMERIC(18,2),
          rate_pct NUMERIC(6,4) NOT NULL,
          effective_date DATE NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ptkp_ter_category_map (
          ptkp_status ptkp_status_enum PRIMARY KEY,
          ter_category VARCHAR(2) NOT NULL CHECK
            (ter_category IN ('A','B','C'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE overtime_multiplier_config (
          entity_id UUID PRIMARY KEY REFERENCES entities(id),
          multiplier NUMERIC(4,2) NOT NULL DEFAULT 1.5,
          effective_date DATE NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE payroll_periods (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_id UUID NOT NULL REFERENCES entities(id),
          period_year SMALLINT NOT NULL,
          period_month SMALLINT NOT NULL CHECK
            (period_month BETWEEN 1 AND 12),
          start_date DATE NOT NULL,
          end_date DATE NOT NULL,
          status payroll_period_status_enum NOT NULL DEFAULT 'DRAFT',
          approved_by UUID REFERENCES user_profiles(id),
          approved_at TIMESTAMPTZ,
          ap_gaji_account_id UUID REFERENCES chart_of_accounts(id),
          accrual_journal_entry_id UUID REFERENCES journal_entries(id),
          disbursed_by UUID REFERENCES user_profiles(id),
          disbursed_at TIMESTAMPTZ,
          journal_entry_id UUID REFERENCES journal_entries(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entity_id, period_year, period_month)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE payroll_entries (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          payroll_period_id UUID NOT NULL REFERENCES payroll_periods(id),
          employee_id UUID NOT NULL REFERENCES employees(id),
          working_days INT NOT NULL,
          unpaid_days INT NOT NULL DEFAULT 0,
          overtime_hours NUMERIC(6,2) NOT NULL DEFAULT 0,
          gross_earning NUMERIC(18,2) NOT NULL DEFAULT 0,
          total_deduction NUMERIC(18,2) NOT NULL DEFAULT 0,
          net_pay NUMERIC(18,2) NOT NULL DEFAULT 0,
          calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (payroll_period_id, employee_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE payroll_entry_lines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          payroll_entry_id UUID NOT NULL REFERENCES payroll_entries(id)
            ON DELETE CASCADE,
          component_code VARCHAR(30) NOT NULL
            REFERENCES payroll_component_master(code),
          amount NUMERIC(18,2) NOT NULL,
          note VARCHAR(200)
        )
        """
    )

    # ------------------------------------------------------------------
    # RLS — payroll data is sensitive: finance roles see their entity,
    # employees (with a user profile) see only their own entries.
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE employees ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE company_calendar ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE attendance_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE overtime_multiplier_config ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payroll_periods ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payroll_entries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payroll_entry_lines ENABLE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY employees_entity_policy ON employees FOR ALL USING (
          entity_id = fn_current_entity_id()
        )
        """
    )
    op.execute(
        """
        CREATE POLICY calendar_entity_policy ON company_calendar FOR ALL USING (
          entity_id = fn_current_entity_id()
        )
        """
    )
    op.execute(
        """
        CREATE POLICY attendance_entity_policy ON attendance_records
        FOR ALL USING (
          EXISTS (
            SELECT 1 FROM employees e
            WHERE e.id = attendance_records.employee_id
              AND e.entity_id = fn_current_entity_id()
          )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY ot_multiplier_entity_policy
        ON overtime_multiplier_config FOR ALL USING (
          entity_id = fn_current_entity_id()
        )
        """
    )
    op.execute(
        """
        CREATE POLICY payroll_periods_entity_policy
        ON payroll_periods FOR ALL USING (
          entity_id = fn_current_entity_id()
        )
        """
    )
    op.execute(
        """
        CREATE POLICY payroll_select_scoped ON payroll_entries FOR SELECT USING (
          fn_current_role() IN ('FINANCE_OPERATOR','DEPT_HEAD_FA','SUPER_ADMIN')
          AND EXISTS (
            SELECT 1 FROM payroll_periods pp
            WHERE pp.id = payroll_entries.payroll_period_id
              AND pp.entity_id = fn_current_entity_id()
          )
          OR employee_id IN (
            SELECT e.id FROM employees e
            WHERE e.user_profile_id = fn_current_user_id()
          )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY payroll_lines_select_scoped
        ON payroll_entry_lines FOR SELECT USING (
          EXISTS (
            SELECT 1 FROM payroll_entries pe
            WHERE pe.id = payroll_entry_lines.payroll_entry_id
              AND (
                (fn_current_role() IN
                   ('FINANCE_OPERATOR','DEPT_HEAD_FA','SUPER_ADMIN')
                 AND EXISTS (
                   SELECT 1 FROM payroll_periods pp
                   WHERE pp.id = pe.payroll_period_id
                     AND pp.entity_id = fn_current_entity_id()
                 ))
                OR pe.employee_id IN (
                  SELECT e.id FROM employees e
                  WHERE e.user_profile_id = fn_current_user_id()
                )
              )
          )
        )
        """
    )
    # Ledger-like immutability: lifecycle transitions only happen inside
    # the SECURITY DEFINER RPCs (function owner bypasses these revokes).
    op.execute(
        "REVOKE UPDATE, DELETE ON payroll_periods, payroll_entries, "
        "payroll_entry_lines FROM PUBLIC"
    )

    # ------------------------------------------------------------------
    # Seed data (config-driven)
    # ------------------------------------------------------------------
    comp_rows = ", ".join(
        f"('{code}', '{name}', '{typ}', {taxable})"
        for code, name, typ, taxable in COMPONENTS
    )
    op.execute(
        "INSERT INTO payroll_component_master "
        "(code, name, type, is_taxable) VALUES " + comp_rows
    )

    bpjs_rows = ", ".join(
        f"('{code}', {ee}, {er}, "
        f"{cap if cap is not None else 'NULL'}, DATE '{eff}')"
        for code, ee, er, cap, eff in BPJS_RATES
    )
    op.execute(
        "INSERT INTO bpjs_rate_config (component_code, employee_rate_pct, "
        "employer_rate_pct, salary_cap, effective_date) VALUES " + bpjs_rows
    )

    ptkp_rows = ", ".join(f"('{st}', '{cat}')" for st, cat in PTKP_TER_MAP)
    op.execute(
        "INSERT INTO ptkp_ter_category_map (ptkp_status, ter_category) "
        "VALUES " + ptkp_rows
    )

    ter_rows = []
    for cat, table in (("A", TER_A), ("B", TER_B), ("C", TER_C)):
        for frm, to, rate in table:
            to_sql = f"{to}" if to is not None else "NULL"
            ter_rows.append(
                f"('{cat}', {frm}, {to_sql}, {rate}, DATE '2024-01-01')"
            )
    op.execute(
        "INSERT INTO tax_pph21_ter_table "
        "(ter_category, income_from, income_to, rate_pct, effective_date) "
        "VALUES " + ", ".join(ter_rows)
    )

    # ------------------------------------------------------------------
    # RPC: fn_calculate_payroll_entry
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_calculate_payroll_entry(
          p_employee_id UUID, p_payroll_period_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_employee        employees%ROWTYPE;
          v_period          payroll_periods%ROWTYPE;
          v_working_days    INT;
          v_unpaid_days     INT;
          v_overtime_hours  NUMERIC(6,2);
          v_hourly_rate     NUMERIC(18,2);
          v_overtime_multiplier NUMERIC(4,2);
          v_overtime_pay    NUMERIC(18,2) := 0;
          v_denda_unpaid    NUMERIC(18,2) := 0;
          v_gross_earning   NUMERIC(18,2) := 0;
          v_basic_line      NUMERIC(18,2);
          v_bpjs            RECORD;
          v_bpjs_amount     NUMERIC(18,2);
          v_bpjs_ee_total   NUMERIC(18,2) := 0;
          v_bpjs_lines      JSONB := '[]'::jsonb;
          v_ter_category    VARCHAR(2);
          v_ter_rate        NUMERIC(6,4);
          v_pph21           NUMERIC(18,2) := 0;
          v_total_deduction NUMERIC(18,2);
          v_net_pay         NUMERIC(18,2);
          v_entry_id        UUID;
        BEGIN
          IF fn_current_role() NOT IN
             ('FINANCE_OPERATOR','DEPT_HEAD_FA','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Only finance roles can calculate payroll.');
          END IF;

          SELECT * INTO v_employee FROM employees
          WHERE id = p_employee_id AND is_active = TRUE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('EMPLOYEE_NOT_FOUND',
              'Karyawan tidak ditemukan atau nonaktif.');
          END IF;

          IF fn_current_entity_id() IS DISTINCT FROM v_employee.entity_id THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only calculate payroll for your own entity.');
          END IF;

          SELECT * INTO v_period FROM payroll_periods
          WHERE id = p_payroll_period_id FOR UPDATE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('PERIOD_NOT_FOUND',
              'Periode payroll tidak ditemukan.');
          END IF;
          IF v_period.status <> 'DRAFT' THEN
            PERFORM fn_raise_error('PERIOD_NOT_DRAFT',
              'Kalkulasi hanya dapat dilakukan pada periode DRAFT.');
          END IF;

          IF EXISTS (
            SELECT 1 FROM payroll_entries
            WHERE employee_id = p_employee_id
              AND payroll_period_id = p_payroll_period_id
          ) THEN
            PERFORM fn_raise_error('ENTRY_ALREADY_EXISTS',
              'Payroll entry untuk karyawan ini pada periode ini sudah ada.');
          END IF;

          SELECT COUNT(*) INTO v_working_days FROM company_calendar
          WHERE entity_id = v_employee.entity_id
            AND calendar_date BETWEEN v_period.start_date AND v_period.end_date
            AND is_working_day = TRUE;
          IF v_working_days = 0 THEN
            PERFORM fn_raise_error('CALENDAR_NOT_PROVISIONED',
              'Company calendar untuk periode ini belum di-setup.');
          END IF;

          SELECT COUNT(*) FILTER (WHERE status = 'UNPAID_LEAVE'),
                 COALESCE(SUM(overtime_hours), 0)
          INTO v_unpaid_days, v_overtime_hours
          FROM attendance_records
          WHERE employee_id = p_employee_id
            AND work_date BETWEEN v_period.start_date AND v_period.end_date;

          -- Overtime: Rate/Jam = (1/173) x Gaji Pokok (both types)
          v_hourly_rate := ROUND(v_employee.base_salary / 173.0, 2);
          SELECT multiplier INTO v_overtime_multiplier
          FROM overtime_multiplier_config
          WHERE entity_id = v_employee.entity_id;
          v_overtime_multiplier := COALESCE(v_overtime_multiplier, 1.5);
          v_overtime_pay := ROUND(
            v_overtime_hours * v_hourly_rate * v_overtime_multiplier, 2);

          IF v_employee.employment_type = 'DAILY' THEN
            -- DAILY: base_salary is a per-day rate; pay only days worked.
            v_gross_earning :=
              (v_employee.base_salary
                 * GREATEST(v_working_days - v_unpaid_days, 0))
              + v_overtime_pay;
            v_basic_line :=
              v_employee.base_salary
                 * GREATEST(v_working_days - v_unpaid_days, 0);
          ELSE
            -- MONTHLY: full base salary, unpaid days penalized separately.
            v_denda_unpaid := ROUND(
              (v_unpaid_days::numeric / v_working_days)
              * v_employee.base_salary, 2);
            v_gross_earning := v_employee.base_salary + v_overtime_pay;
            v_basic_line := v_employee.base_salary;
          END IF;

          -- BPJS (employee portion), basis capped per config
          FOR v_bpjs IN
            SELECT * FROM bpjs_rate_config
            WHERE component_code LIKE 'BPJS\_%\_EE'
            ORDER BY component_code
          LOOP
            v_bpjs_amount := ROUND(
              LEAST(v_employee.base_salary,
                    COALESCE(v_bpjs.salary_cap, v_employee.base_salary))
              * v_bpjs.employee_rate_pct / 100, 2);
            v_bpjs_ee_total := v_bpjs_ee_total + v_bpjs_amount;
            v_bpjs_lines := v_bpjs_lines || jsonb_build_object(
              'component_code', v_bpjs.component_code,
              'amount', -v_bpjs_amount);
          END LOOP;

          -- PPh 21 TER: category from PTKP status, bracket from gross
          SELECT ter_category INTO v_ter_category
          FROM ptkp_ter_category_map
          WHERE ptkp_status = v_employee.ptkp_status;
          IF v_ter_category IS NULL THEN
            PERFORM fn_raise_error('TER_CATEGORY_NOT_FOUND',
              'Kategori TER untuk status PTKP karyawan belum dikonfigurasi.');
          END IF;

          SELECT rate_pct INTO v_ter_rate FROM tax_pph21_ter_table
          WHERE ter_category = v_ter_category
            AND v_gross_earning > income_from
            AND (income_to IS NULL OR v_gross_earning <= income_to)
            AND effective_date <= v_period.start_date
          ORDER BY effective_date DESC LIMIT 1;
          IF v_ter_rate IS NULL THEN
            PERFORM fn_raise_error('TER_RATE_NOT_FOUND',
              'Bracket TER untuk penghasilan bruto ini belum dikonfigurasi.');
          END IF;
          v_pph21 := ROUND(v_gross_earning * v_ter_rate / 100, 2);

          v_total_deduction := v_denda_unpaid + v_bpjs_ee_total + v_pph21;
          v_net_pay := v_gross_earning - v_total_deduction;

          INSERT INTO payroll_entries (
            payroll_period_id, employee_id, working_days, unpaid_days,
            overtime_hours, gross_earning, total_deduction, net_pay
          ) VALUES (
            p_payroll_period_id, p_employee_id, v_working_days,
            v_unpaid_days, v_overtime_hours,
            v_gross_earning, v_total_deduction, v_net_pay
          ) RETURNING id INTO v_entry_id;

          INSERT INTO payroll_entry_lines
            (payroll_entry_id, component_code, amount)
          VALUES
            (v_entry_id, 'BASIC', v_basic_line),
            (v_entry_id, 'OVERTIME', v_overtime_pay),
            (v_entry_id, 'DENDA_UNPAID', -v_denda_unpaid),
            (v_entry_id, 'PPH21', -v_pph21);

          INSERT INTO payroll_entry_lines
            (payroll_entry_id, component_code, amount)
          SELECT v_entry_id, bl->>'component_code', (bl->>'amount')::numeric
          FROM jsonb_array_elements(v_bpjs_lines) bl;

          INSERT INTO system_logs
            (actor_id, entity_id, action, table_name, record_id, after_data)
          VALUES (
            fn_current_user_id(), v_employee.entity_id, 'CALCULATE',
            'payroll_entries', v_entry_id::text,
            jsonb_build_object('net_pay', v_net_pay,
                               'gross_earning', v_gross_earning));

          RETURN jsonb_build_object('success', TRUE,
            'payroll_entry_id', v_entry_id, 'net_pay', v_net_pay);
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC: fn_approve_payroll_period (accrual posting)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_approve_payroll_period(
          p_payroll_period_id UUID, p_ap_gaji_account_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_period payroll_periods%ROWTYPE;
          v_uncalculated_count INT;
          v_component RECORD;
          v_total_net NUMERIC(18,2);
          v_je_lines JSONB := '[]'::jsonb;
          v_je_result JSONB;
        BEGIN
          IF fn_current_role() NOT IN ('DEPT_HEAD_FA','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Hanya Head of F&A atau Super Admin dapat approve payroll.');
          END IF;

          SELECT * INTO v_period FROM payroll_periods
          WHERE id = p_payroll_period_id FOR UPDATE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('PERIOD_NOT_FOUND',
              'Periode payroll tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_period.entity_id THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only approve payroll for your own entity.');
          END IF;
          IF v_period.status <> 'DRAFT' AND v_period.status <> 'CALCULATED'
          THEN
            PERFORM fn_raise_error('PERIOD_INVALID_STATUS',
              format('Periode berstatus %s, harus DRAFT/CALCULATED.',
                     v_period.status));
          END IF;

          SELECT COUNT(*) INTO v_uncalculated_count FROM employees e
          WHERE e.entity_id = v_period.entity_id AND e.is_active = TRUE
            AND NOT EXISTS (
              SELECT 1 FROM payroll_entries pe
              WHERE pe.employee_id = e.id
                AND pe.payroll_period_id = p_payroll_period_id);
          IF v_uncalculated_count > 0 THEN
            PERFORM fn_raise_error('INCOMPLETE_CALCULATION',
              format('%s karyawan aktif belum dihitung payroll-nya.',
                     v_uncalculated_count));
          END IF;

          -- Accrual: Dr EARNING components, Cr DEDUCTION components,
          -- Cr AP Gaji (net). Skips zero-total lines to keep the journal
          -- clean.
          FOR v_component IN
            SELECT pel.component_code, pcm.type, pcm.gl_account_id,
                   SUM(pel.amount) AS total_amount
            FROM payroll_entry_lines pel
            JOIN payroll_entries pe ON pe.id = pel.payroll_entry_id
            JOIN payroll_component_master pcm
              ON pcm.code = pel.component_code
            WHERE pe.payroll_period_id = p_payroll_period_id
            GROUP BY pel.component_code, pcm.type, pcm.gl_account_id
          LOOP
            IF v_component.total_amount = 0 THEN
              CONTINUE;
            END IF;
            IF v_component.gl_account_id IS NULL THEN
              PERFORM fn_raise_error('COMPONENT_GL_ACCOUNT_MISSING',
                format('Komponen payroll %s belum punya gl_account_id.',
                       v_component.component_code));
            END IF;
            IF v_component.type = 'EARNING' THEN
              v_je_lines := v_je_lines || jsonb_build_object(
                'account_id', v_component.gl_account_id,
                'debit_amount', v_component.total_amount,
                'credit_amount', 0);
            ELSE
              v_je_lines := v_je_lines || jsonb_build_object(
                'account_id', v_component.gl_account_id,
                'debit_amount', 0,
                'credit_amount', ABS(v_component.total_amount));
            END IF;
          END LOOP;

          SELECT COALESCE(SUM(net_pay), 0) INTO v_total_net
          FROM payroll_entries
          WHERE payroll_period_id = p_payroll_period_id;
          IF v_total_net <= 0 THEN
            PERFORM fn_raise_error('NOTHING_TO_DISBURSE',
              'Tidak ada net pay pada periode ini.');
          END IF;
          v_je_lines := v_je_lines || jsonb_build_object(
            'account_id', p_ap_gaji_account_id,
            'debit_amount', 0, 'credit_amount', v_total_net);

          v_je_result := fn_create_journal_entry(
            v_period.entity_id, v_period.end_date,
            format('Payroll Accrual %s-%s',
                   v_period.period_month, v_period.period_year),
            'IDR', v_je_lines);
          PERFORM fn_post_journal_entry(
            (v_je_result->>'journal_entry_id')::uuid);

          UPDATE payroll_periods
          SET status = 'APPROVED', approved_by = fn_current_user_id(),
              approved_at = now(),
              ap_gaji_account_id = p_ap_gaji_account_id,
              accrual_journal_entry_id =
                (v_je_result->>'journal_entry_id')::uuid
          WHERE id = p_payroll_period_id;

          INSERT INTO system_logs
            (actor_id, entity_id, action, table_name, record_id, after_data)
          VALUES (
            fn_current_user_id(), v_period.entity_id, 'APPROVE',
            'payroll_periods', p_payroll_period_id::text,
            jsonb_build_object('status', 'APPROVED',
              'accrual_journal_entry_id',
              v_je_result->>'journal_entry_id'));

          RETURN jsonb_build_object('success', TRUE,
            'period_id', p_payroll_period_id, 'status', 'APPROVED',
            'journal_entry_id', v_je_result->>'journal_entry_id');
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # RPC: fn_disburse_payroll_period (payment posting)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_disburse_payroll_period(
          p_payroll_period_id UUID, p_kas_bank_account_id UUID
        ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
        DECLARE
          v_period payroll_periods%ROWTYPE;
          v_total_net NUMERIC(18,2);
          v_je_result JSONB;
          v_je_id UUID;
        BEGIN
          IF fn_current_role() NOT IN ('DEPT_HEAD_FA','SUPER_ADMIN') THEN
            PERFORM fn_raise_error('FORBIDDEN_ROLE',
              'Hanya Head of F&A atau Super Admin dapat disburse payroll.');
          END IF;

          SELECT * INTO v_period FROM payroll_periods
          WHERE id = p_payroll_period_id FOR UPDATE;
          IF NOT FOUND THEN
            PERFORM fn_raise_error('PERIOD_NOT_FOUND',
              'Periode payroll tidak ditemukan.');
          END IF;
          IF fn_current_entity_id() IS DISTINCT FROM v_period.entity_id THEN
            PERFORM fn_raise_error('FORBIDDEN_ENTITY',
              'You can only disburse payroll for your own entity.');
          END IF;
          IF v_period.status <> 'APPROVED' THEN
            PERFORM fn_raise_error('PERIOD_NOT_APPROVED',
              'Disbursement hanya bisa setelah periode APPROVED.');
          END IF;

          SELECT COALESCE(SUM(net_pay), 0) INTO v_total_net
          FROM payroll_entries
          WHERE payroll_period_id = p_payroll_period_id;
          IF v_total_net <= 0 THEN
            PERFORM fn_raise_error('NOTHING_TO_DISBURSE',
              'Tidak ada net pay untuk didisbursement pada periode ini.');
          END IF;

          v_je_result := fn_create_journal_entry(
            v_period.entity_id, v_period.end_date,
            format('Payroll Disbursement %s-%s',
                   v_period.period_month, v_period.period_year),
            'IDR',
            jsonb_build_array(
              jsonb_build_object('account_id', v_period.ap_gaji_account_id,
                'debit_amount', v_total_net, 'credit_amount', 0),
              jsonb_build_object('account_id', p_kas_bank_account_id,
                'debit_amount', 0, 'credit_amount', v_total_net)
            ));
          v_je_id := (v_je_result->>'journal_entry_id')::uuid;
          PERFORM fn_post_journal_entry(v_je_id);

          UPDATE payroll_periods
          SET status = 'DISBURSED', disbursed_by = fn_current_user_id(),
              disbursed_at = now(), journal_entry_id = v_je_id
          WHERE id = p_payroll_period_id;

          INSERT INTO system_logs
            (actor_id, entity_id, action, table_name, record_id, after_data)
          VALUES (
            fn_current_user_id(), v_period.entity_id, 'DISBURSE',
            'payroll_periods', p_payroll_period_id::text,
            jsonb_build_object('journal_entry_id', v_je_id,
                               'total_net', v_total_net));

          RETURN jsonb_build_object('success', TRUE,
            'period_id', p_payroll_period_id,
            'journal_entry_id', v_je_id, 'total_net', v_total_net);
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS fn_disburse_payroll_period(UUID, UUID)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS fn_approve_payroll_period(UUID, UUID)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS fn_calculate_payroll_entry(UUID, UUID)"
    )
    op.execute("DROP TABLE IF EXISTS payroll_entry_lines CASCADE")
    op.execute("DROP TABLE IF EXISTS payroll_entries CASCADE")
    op.execute("DROP TABLE IF EXISTS payroll_periods CASCADE")
    op.execute("DROP TABLE IF EXISTS overtime_multiplier_config CASCADE")
    op.execute("DROP TABLE IF EXISTS ptkp_ter_category_map CASCADE")
    op.execute("DROP TABLE IF EXISTS tax_pph21_ter_table CASCADE")
    op.execute("DROP TABLE IF EXISTS bpjs_rate_config CASCADE")
    op.execute("DROP TABLE IF EXISTS payroll_component_master CASCADE")
    op.execute("DROP TABLE IF EXISTS attendance_records CASCADE")
    op.execute("DROP TABLE IF EXISTS company_calendar CASCADE")
    op.execute("DROP TABLE IF EXISTS employees CASCADE")
    op.execute("DROP TYPE IF EXISTS ptkp_status_enum")
    op.execute("DROP TYPE IF EXISTS component_type_enum")
    op.execute("DROP TYPE IF EXISTS payroll_period_status_enum")
    op.execute("DROP TYPE IF EXISTS employment_type_enum")
