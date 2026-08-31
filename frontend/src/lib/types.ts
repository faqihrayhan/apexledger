/**
 * Shared backend contract types for the General Ledger module.
 *
 * Mirrors the Pydantic schemas in `backend/app/schemas/gl.py` and
 * `backend/app/schemas/coa.py`. Amounts arrive as strings to preserve
 * decimal precision (financial best practice) — parse with a Decimal
 * helper when doing arithmetic.
 */

/* ------------------------------- auth ----------------------------------- */

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  role: string;
}

export interface SetupStatus {
  is_initialized: boolean;
}

/* ------------------------------- journals ------------------------------- */

export interface JournalLineIn {
  account_id: string;
  debit_amount: string;
  credit_amount: string;
  department_code?: string | null;
  description?: string | null;
}

export interface JournalCreateRequest {
  journal_date: string;
  description?: string | null;
  currency_code: string;
  lines: JournalLineIn[];
}

export interface JournalCreateResponse {
  journal_entry_id: string;
  journal_number: string;
  status: string;
}

export interface JournalPostResponse {
  journal_entry_id: string;
  status: string;
  debit_total: string;
  credit_total: string;
}

export interface JournalReverseRequest {
  reversal_date: string;
  reason?: string | null;
}

export interface JournalReverseResponse {
  original_entry_id: string;
  original_status: string;
  reversal_entry_id: string;
  reversal_number: string;
}

export interface JournalSummary {
  id: string;
  journal_number: string;
  journal_date: string;
  description: string | null;
  status: "DRAFT" | "POSTED" | "REVERSED" | string;
  is_reversal: boolean;
  currency_code: string;
  total_amount: string;
  line_count: number;
}

/* -------------------------------- accounts ------------------------------- */

export interface AccountOut {
  id: string;
  entity_id: string;
  account_code: string;
  account_name: string;
  account_type: string;
  normal_balance: "DEBIT" | "CREDIT" | string;
  parent_account_id: string | null;
  level: number;
  is_postable: boolean;
  is_active: boolean;
}

/* ----------------------------- trial balance ----------------------------- */

export interface TrialBalanceRow {
  account_id: string;
  account_code: string;
  account_name: string;
  account_type: string;
  normal_balance: string;
  total_debit: string;
  total_credit: string;
  net_debit: string;
  net_credit: string;
}

export interface TrialBalanceReport {
  as_of_date: string;
  entity_id: string;
  rows: TrialBalanceRow[];
  grand_total_debit: string;
  grand_total_credit: string;
  is_balanced: boolean;
}
