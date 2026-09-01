# Module Reference

ApexLedger is organized into **eight modules (M1–M8)**, each implemented end-to-end — schema → RLS → PL/pgSQL RPCs → API → tests — and all of them posting into **one general ledger**. This page maps the territory; the daily flows have their own guides.

## The module map

| Module | Code | Scope | Guide |
|---|---|---|---|
| General Ledger & CoA | M1 | double-entry engine, chart of accounts, posting/reversal, trial balance | [Daily Journal Entry](/docs/journals) |
| Payroll | M2 | TER & BPJS calculation, approval, disbursement | this page |
| Inventory & Work Orders | M3 | warehouses, items, costing, BOM manufacturing | this page |
| Order-to-Cash & POS | M4 | credit-gated sales, delivery, AR invoicing, returns | [Order-to-Cash](/docs/order-to-cash) |
| Procure-to-Pay | M5 | PO approval engine, inspection, 3-way match, payments | [Procure-to-Pay](/docs/procure-to-pay) |
| Treasury | M6 | kasbon lifecycle, bank reconciliation, cash-flow forecast | this page |
| Fixed Assets | M7 | registration, depreciation batches, disposal | this page |
| Budgeting & Analytics | M8 | budget cycle, vs-actual, trends, productivity | this page |

## Payroll (M2)

Indonesian payroll as data, not spreadsheets:

- **Calculate** — per employee, per period. The RPC joins the **company calendar** (working days), applies unpaid-day deductions, overtime (hourly rate = base ÷ **173**, rounded first then multiplied), **BPJS** components from seeded rate config, and the official **TER bracket table (PMK 168/2023 — 125 brackets)** against the employee's PTKP category.
- **Approve** — posts the accrual journal: Dr Earnings expense / Cr Deductions payable + Cr AP Gaji.
- **Disburse** — posts Dr AP Gaji / Cr cash-bank. Per-employee math is auditable from the Entries drill-down.
- Guards: `ENTRY_ALREADY_EXISTS` (double calculate), `INCOMPLETE_CALCULATION` (approve early), `CALENDAR_NOT_PROVISIONED`, `PERIOD_NOT_APPROVED`.

## Inventory & Work Orders (M3)

- **Costing** — moving average (recomputed on every receipt: `(old_avg × old_qty + line_total) / new_qty`) or **FIFO** (burns oldest cost layers); **FEFO** for expiry-dated items (nearest-expiry first, expired lots skipped).
- **No negative stock** — aggregated availability is checked **before** any lot burn; drift between lot table and aggregate raises `LOT_STOCK_DRIFT` and blocks the issue.
- **Transfers** — atomic issue + receive between warehouses **of the same entity**; cross-entity transfers are rejected.
- **Work orders** — BOM (components + waste %) + labor + FOH rate (overhead ÷ capacity). Completing consumes components pro-rata to yield, computes **COGM = material + labor + FOH**, breaks material down **per inventory account**, and posts Dr Finished Goods / Cr components / Cr labor / Cr FOH.

## Treasury (M6)

- **Kasbon (employee advances)** — request → submit → the **same dynamic approval engine as procurement** stamps the required role → approve → disburse → **settle**. Settlement splits automatically: used ≤ amount posts expenses; leftover cash returns to the bank; overage becomes an additional employee claim. The receivable clears to zero.
- **Bank reconciliation** — import statement lines, then **Auto-match**: exact amount within **±3 days** matches AR/AP payments. Unmatched lines stay flagged for manual review.
- **Cash-flow forecast** — read-only weekly projection: AR due dates (inflow) vs AP due dates + pending kasbon (outflow).

## Fixed Assets (M7)

- **Register** — cost, salvage, useful life (months), straight-line or declining balance. Codes `FA-YYYY-XXXXXX`; the acquisition journal auto-posts.
- **Depreciation** — monthly batch (built-in scheduler: 01:00 on day 1, for the previous month), **one aggregated journal per run**. Straight-line: (cost − salvage) ÷ life, **capped so book value never drops below salvage**. Fully depreciated assets flip to `FULLY_DEPRECIATED`.
- **Dispose** — sale / write-off / donation; the RPC posts the full sign-aware exit journal (accumulated depreciation + proceeds ± loss/gain vs cost). Codes stay for audit.

## Budgeting & Analytics (M8)

- **Cycle** — create (account × department × month × amount) → approve (DEPT_HEAD_FA) → **lock** (SUPER_ADMIN only; frozen for normal revision).
- **Revise** — requires a reason; snapshots the before-state (JSONB), deletes and reinserts lines atomically, increments the revision number. Even locked budgets can be revised by SUPER_ADMIN — with the trail intact.
- **Vs-actual** — joins POSTED journal lines per fiscal year against budget lines: budgeted, actual, variance amount and %.
- **Trend** — REVENUE / EXPENSE movement over the last N months, normal-balance aware.

## How the modules connect

Every module ends its flow by **posting a journal into M1** — payroll accruals, depreciation batches, COGM entries, AP/AR invoices. The [month-end close](/docs/month-end-close) is simply the moment all those postings are verified and the period locks. One ledger, one truth.

## What's next

- [Installation](/docs/installation) — get a server running.
- `docs/USER_FLOWS.md` in the repository — every flow above, in full detail.
