# User Flows

End-to-end operational flows across ApexLedger modules, written from the
actual API contracts and database-enforced state machines. Use this as
the reference for onboarding, training, and QA walkthroughs.

Each flow lists: the actors (roles), the happy path step by step, the
state transitions enforced by the engine, and the guard rails that block
invalid paths.

> Roles are referenced by code. See the Role Reference section at the
> end for the full list and what each can do.

## Contents

1. First-Boot Setup
2. Daily Journal Entry (GL)
3. Month-End Close
4. Procure-to-Pay (M5)
5. Order-to-Cash (M4)
6. Inventory Receiving & Work Orders (M3)
7. Payroll Run (M2)
8. Treasury — Kasbon & Reconciliation (M6)
9. Fixed Asset Lifecycle (M7)
10. Budget Cycle (M8)
11. Role Reference

---

## 1. First-Boot Setup

**Actor:** the first user (becomes SUPER_ADMIN)

1. Fresh database → the frontend Login page detects
   `GET /api/v1/system/status` → `is_initialized: false` → renders the
   **Setup Wizard** instead of the login form.
2. Fill the wizard:
   - Entity code + name (company identity)
   - Base currency (default `IDR`)
   - Admin full name, email, password (min 8 chars)
   - Fiscal year (e.g. `2026`)
3. `POST /api/v1/system/setup` — **one atomic transaction** creates:
   entity → SUPER_ADMIN user → fiscal year → 12 monthly periods →
   audit log entry. Returns the first `access_token`.
4. The app is ready. Subsequent users are created via
   `POST /api/v1/auth/register` with an explicit role.

**Guards:** setup is once-only — a second call is rejected by the
engine. `register` requires an `entity_id` once the instance is
initialized.

---

## 2. Daily Journal Entry (GL)

**Actors:** any accounting role (FINANCE_OPERATOR and above)

1. **Chart of accounts** — before anything posts, create accounts via
   the Accounts page (`POST /gl/accounts`). Account codes are unique
   per entity. Deleting an account with history is blocked (soft-delete
   only).
2. **Draft the entry** — New Journal page: pick a date, add lines
   (account, debit/credit, description). The form shows a **live
   balance meter** (BigInt cents math); the submit button stays
   disabled until debits equal credits.
3. `POST /gl/journal-entries` — the RPC validates balance again
   inside PostgreSQL and assigns a number `JE-YYYYMM-NNNNN` from a
   per-entity sequence. Status: `DRAFT`.
4. **Post** — from the Journals list, hit Post. `fn_post_journal_entry`
   flips DRAFT → POSTED. POSTED entries are **immutable** — no UPDATE
   or DELETE grants exist on `journal_entries` at the database level.
5. **Correct a mistake** — never edit. Issue a **reversal**
   (`POST /gl/journal-entries/{id}/reverse`): the engine creates a
   mirrored entry with inverted debit/credit lines and links it back.
   Original status becomes `REVERSED`.
6. **Verify** — Trial Balance page (`POST /gl/reports/trial-balance`)
   shows net debit/credit per account with as-of date filtering and a
   `is_balanced` proof (grand totals must match).

**Guards:** unbalanced entries are rejected by the RPC (JE_UNBALANCED),
not by the UI. Posted entries can only be reversed, never mutated.

---

## 3. Month-End Close

**Actor:** FINANCE_OPERATOR / DEPT_HEAD_FA

1. Ensure all source-module journals are posted (payroll accruals,
   depreciation batches, POS batch journals — each module's posting
   step below feeds this).
2. Run **Trial Balance as-of** the last day of the month; confirm
   `is_balanced: true`.
3. Review monthly trends (Budgeting → Trend, REVENUE and EXPENSE) for
   anomalies before closing.
4. New transactions in a closed period are rejected by the engine
   (PERIOD_NOT_FOUND / period status checks) — closing is enforced by
   the fiscal_periods table, not by convention.

---

## 4. Procure-to-Pay (M5)

**Actors:** FINANCE_OPERATOR (creates PO), approval role (dynamic),
WAREHOUSE_OPERATOR (receives), FINANCE (bill + payment)

1. **Vendor master** — Procurement → Vendors: add vendor with payment
   terms (days) and NPWP.
2. **Purchase order** — create PO with lines (item, qty, unit price)
   → status `DRAFT`.
3. **Submit** — `fn_submit_purchase_order` runs the **dynamic approval
   engine**: reads `approval_thresholds` (min_amount DESC) and stamps
   the required role on the PO. Small values may auto-approve; large
   values can require DIREKSI. Status → `PENDING_APPROVAL`.
4. **Approve** — a user whose role ≥ the required role calls approve
   → `CONFIRMED`-equivalent (`APPROVED`). Insufficient authority
   returns INSUFFICIENT_APPROVAL_AUTHORITY from the RPC.
5. **Receive goods** — WAREHOUSE_OPERATOR records a Goods Received
   Note per PO. Stock is **not** booked yet (PUTG — Pending Untested
   Goods). Status → `PARTIALLY_RECEIVED` / `RECEIVED`.
6. **Inspect (PUTG)** — per line, enter accepted vs rejected qty.
   Accepted goods flow into stock at PO price via `fn_receive_stock`;
   the GL posts Dr Inventory / Cr GR-IR clearing. Rejected goods never
   enter stock. GRN status → `PASSED` / `PARTIAL` / `REJECTED`.
7. **AP bill** — finance creates a bill from a PASSED/PARTIAL GRN
   (one bill per GRN). Due date = bill date + vendor terms.
8. **3-way match** — `fn_match_and_approve_ap_bill` compares bill qty
   vs GRN accepted qty and price vs PO price (±2%). Mismatch → status
   `DISPUTED` with a reason, no GL. Match → GL posts Dr GR-IR +
   Dr PPN Masukan + price variance / Cr AP.
9. **Pay** — `fn_record_ap_payment` posts Dr AP / Cr cash-bank,
   allocates FIFO by due date, bill → `PAID`.

**Side flows:** purchase return (debit note, stock out at cost basis,
Dr AP / Cr Inventory / Cr PPN); landed cost allocation (capitalize
freight/customs into item cost by qty/value/weight).

**Guards:** receive before approve → PO_INVALID_STATUS; over-receipt →
RECEIPT_EXCEEDS_ORDER; bill from un-inspected GRN → GRN_NOT_INSPECTED;
double inspection, double billing → status guards.

---

## 5. Order-to-Cash (M4)

**Actors:** SALES_OPERATOR (orders), WAREHOUSE_OPERATOR (delivery),
FINANCE_OPERATOR (invoice/payment)

1. **Customer master** — credit limit, payment terms, NPWP.
2. **Sales order** — lines with qty & price → `DRAFT`.
3. **Confirm** — `fn_check_credit_limit` runs *before* confirmation:
   outstanding AR + open orders + this order vs the customer's limit.
   Exceeded → CREDIT_LIMIT_EXCEEDED, SO stays DRAFT. Passed →
   `CONFIRMED`.
4. **Delivery order** — warehouse issues stock per line
   (moving-average cost). Partial deliveries allowed →
   `PARTIALLY_DELIVERED` → `DELIVERED`. Over-delivery is blocked.
5. **AR invoice** — issued from a delivery order (3-way match
   DO↔SO). PPN 11% by default. GL posts Dr AR / Cr Revenue / Cr PPN
   plus Dr COGS / Cr Inventory **per item**.
6. **Payment** — `fn_record_ar_payment` auto-allocates FIFO by due
   date (or explicit allocation), posts Dr Cash / Cr AR. Surplus stays
   unallocated on the invoice. Fully-paid invoice → `PAID`.
7. **Returns** — a sales return receives stock back **at cost basis**
   (never at sale price), issues a credit note (Dr Sales Return /
   Dr PPN / Cr AR + Dr Inventory / Cr COGS), and reduces the
   customer's AR balance.

**Guards:** delivering a DRAFT SO → SO_INVALID_STATUS; double
invoicing → DO_ALREADY_INVOICED; return qty > invoiced qty →
RETURN_QTY_EXCEEDS_INVOICE.

---

## 6. Inventory Receiving & Work Orders (M3)

**Actor:** WAREHOUSE_OPERATOR / DEPT_HEAD_WAREHOUSE

1. **Master** — warehouses first, then items (type: raw material /
   finished good / service / bundle; costing: moving average or
   FIFO; FEFO when the item carries expiry dates; base UoM).
2. **Receive stock** — from procurement inspection or standalone
   receipt. Moving average recomputes on every receipt
   (`(old_avg × old_qty + line_total) / new_qty`). FEFO items require
   an expiry date.
3. **Issue stock** — aggregated availability is checked **before**
   any lot burn (no negative stock). FIFO burns oldest cost layers;
   FEFO burns nearest-expiry first and skips expired lots.
   Drift between lot table and aggregate → LOT_STOCK_DRIFT blocks the
   issue.
4. **Transfer** — atomic issue + receive between warehouses of the
   same entity; cross-entity transfers are rejected.
5. **Work orders** — BOM (components + waste %) + labor + FOH rate
   (overhead ÷ capacity). **Complete** consumes components pro-rata
   to yield, computes COGM = material + labor + FOH, breaks material
   down **per inventory account**, and posts Dr Finished Goods /
   Cr component accounts / Cr labor / Cr FOH. Unit cost banner shows
   COGM ÷ good qty.

**Guards:** receiving without expiry on a FEFO item →
EXPIRY_DATE_REQUIRED; issuing beyond stock → INSUFFICIENT_STOCK;
completing without a FG GL account → FG_ACCOUNT_MISSING.

---

## 7. Payroll Run (M2)

**Actors:** FINANCE_OPERATOR (master + calculate), DEPT_HEAD_FA
(approve), finance (disburse)

1. **Employee master** — code, name, position, department, base
   salary, hire date (bank account + NPWP optional).
2. **Payroll period** — create the month (year, month, start/end
   dates).
3. **Calculate** — per employee, per period. The RPC joins the
   company calendar (working days), applies unpaid-day deductions,
   overtime (hourly rate = base ÷ 173, rounded first, then
   multiplied), BPJS components from seeded rate config, and the
   official **TER bracket table (PMK 168/2023, 125 brackets)** against
   the employee's PTKP category. Result: gross, deductions, net pay
   per entry.
4. **Approve** — posts the accrual journal: Dr Earnings expense /
   Cr Deductions payable + Cr AP Gaji (account picker). Period →
   APPROVED.
5. **Disburse** — posts Dr AP Gaji / Cr cash-bank (account picker).
   Period → DISBURSED. Drill into Entries to audit per-employee math.

**Guards:** calculating twice → ENTRY_ALREADY_EXISTS; approving
before all entries are calculated → INCOMPLETE_CALCULATION; missing
calendar provisioning → CALENDAR_NOT_PROVISIONED; disburse before
approve → PERIOD_NOT_APPROVED.

---

## 8. Treasury — Kasbon & Reconciliation (M6)

**Actors:** requester (any operational role), approver (dynamic
engine), DEPT_HEAD_FA (disburse/settle)

1. **Kasbon request** — employee advance form (amount, purpose,
   department) → `DRAFT`.
2. **Submit** — the same dynamic approval engine as procurement
   stamps the required role from `approval_thresholds`. Status →
   `PENDING_APPROVAL`, the required role is shown on the card.
3. **Approve** — a user at or above the required role approves.
   FINANCE_OPERATOR approving a DIREKSI-level kasbon →
   INSUFFICIENT_APPROVAL_AUTHORITY.
4. **Disburse** — posts Dr Employee receivable / Cr bank (two account
   pickers). Status → `DISBURSED`.
5. **Settle** — enter expense lines (account, description, amount,
   receipt ref). The RPC splits automatically: used ≤ amount posts
   expenses; leftover cash comes back (Dr Bank); overage becomes an
   additional employee claim. The receivable clears to zero. Status →
   `SETTLED`.
6. **Bank reconciliation** — import statement lines (date,
   description, signed amount), then **Auto-match**: exact amount
   within ±3 days matches to AR/AP payments (positive → AR receipt,
   negative → AP payment). Unmatched lines stay flagged for manual
   review.
7. **Cash flow forecast** — read-only weekly projection combining AR
   due dates (inflow), AP due dates + pending kasbon (outflow) over
   the next N weeks.

---

## 9. Fixed Asset Lifecycle (M7)

**Actors:** FINANCE_OPERATOR (register/depreciate), DEPT_HEAD_FA
(dispose)

1. **Register** — name, category (tangible/intangible), acquisition
   date & cost, salvage value, useful life (months), method
   (straight-line or declining balance + rate%). Three account
   pickers: asset, accumulated depreciation, funding source. The RPC
   generates `FA-YYYY-XXXXXX` and auto-posts the acquisition journal
   (Dr Asset / Cr funding). Status → `ACTIVE`.
2. **Monthly depreciation** — run the batch (or let the built-in
   scheduler run it at 01:00 on day 1 for the previous month). One
   **aggregated** journal per run. Straight-line: (cost − salvage) ÷
   life, capped so book value never drops below salvage. Declining:
   rate × book value. Fully depreciated assets are skipped and flip
   to `FULLY_DEPRECIATED`.
3. **Schedule** — per-asset drill-down: monthly depreciation,
   running accumulated, book value after each period.
4. **Dispose** — sale / write-off / donation. The RPC posts the full
   exit journal: Dr accumulated depreciation + Dr proceeds (cash) +
   Dr loss (or Cr gain, sign-aware) / Cr asset cost. Status →
   `DISPOSED`. Asset code stays for audit.

**Guards:** re-running a processed period → PERIOD_ALREADY_PROCESSED;
double disposal → ASSET_ALREADY_DISPOSED; salvage ≥ cost →
INVALID_SALVAGE_VALUE.

---

## 10. Budget Cycle (M8)

**Actors:** DEPT_HEAD_FA (create/revise), SUPER_ADMIN (lock), all
read roles (reports)

1. **Create** — pick the fiscal year, name the budget, add lines
   (account × department × month × amount). Status → `DRAFT`.
2. **Approve** — DRAFT → APPROVED (DEPT_HEAD_FA).
3. **Lock** — APPROVED → LOCKED (SUPER_ADMIN only). Locked budgets
   are frozen for normal revision.
4. **Revise** — requires a reason. The RPC snapshots the current
   lines into `budget_revisions` (full before-state, JSONB), deletes
   and reinserts lines atomically, and increments the revision
   number. Even a locked budget can be revised by SUPER_ADMIN.
5. **Budget vs actual** — pick a month; the report joins POSTED
   journal lines per fiscal year against budget lines: budgeted,
   actual, variance amount and %.
6. **Monthly trend** — REVENUE / EXPENSE movement over the last N
   months, normal-balance aware.
7. **Productivity batch** — idempotent per-employee metrics
   (sales value per employee) for a period; safe to re-run.

**Guards:** approving a non-DRAFT → BUDGET_INVALID_STATUS; empty
budget → BUDGET_EMPTY; revising without a reason → REASON_REQUIRED.

---

## Role Reference

| Role | Typical duties |
|---|---|
| `SUPER_ADMIN` | everything, incl. locking budgets, revising locked budgets |
| `DIREKSI` | board-level approval for high-value POs and kasbons (via thresholds) |
| `DEPT_HEAD_FA` | finance authority: budget create/approve/revise, asset disposal, kasbon disburse/settle |
| `FINANCE_OPERATOR` | day-to-day finance: journals, invoices, payments, payroll calculate, asset register/depreciation |
| `DEPT_HEAD_SALES` | sales authority: SO confirmation, customer master |
| `SALES_OPERATOR` | SO entry, POS sales |
| `DEPT_HEAD_WAREHOUSE` | warehouse authority: GRN, transfers, work orders |
| `WAREHOUSE_OPERATOR` | receiving, issuing, delivery orders |
| `IT_ADMIN` | infrastructure, read-only forecast access |

Approval authority is **dynamic**: `fn_get_required_approval_role` reads
`approval_thresholds` (min_amount DESC) — the required role for a given
amount is data, not code. Role checks in all 30 role-guarded RPCs are
NULL-hardened: a missing role claim is rejected outright (locked by
regression tests).
