# Month-End Close

The close is where the month's activity becomes an official book. The principle is simple: **everything posts to the GL before the period closes, and nothing posts after**. This page is the checklist.

**Actors:** FINANCE_OPERATOR / DEPT_HEAD_FA.

## Step 1 — Post every source-module journal

Each module ends its flow by posting into the general ledger. Before closing, confirm all of them have run:

| Module | What posts | The journal |
|---|---|---|
| Payroll (M2) | **Approve** the payroll period | accrual: Dr Earnings expense / Cr Deductions payable + Cr AP Gaji |
| Payroll (M2) | **Disburse** salaries | Dr AP Gaji / Cr cash-bank |
| Fixed assets (M7) | **Depreciation batch** — monthly, one aggregated journal per run (built-in scheduler runs it at 01:00 on day 1 for the previous month) | Dr Depreciation expense / Cr Accumulated depreciation |
| POS (M4) | **Batch journals** from retail shifts | Dr Cash / Cr Revenue (+ tax lines) |
| Work orders (M3) | **Complete** a work order | Dr Finished goods / Cr components + labor + FOH at COGM |
| Procurement / Sales (M5 / M4) | invoices, payments, receipts | their own journals per flow |

Tip: run the depreciation batch manually if the 01:00 scheduler window was missed — the batch refuses to double-post into a processed period (`PERIOD_ALREADY_PROCESSED`).

## Step 2 — Trial balance, as-of the last day

Run **Trial Balance as-of** the final day of the month (`POST /gl/reports/trial-balance`):

- Net debits and credits per account at the historical cut-off.
- Confirm **`is_balanced: true`** — grand totals match. If the flag is false, chase the anomaly before anything else; see [Daily Journal Entry](/docs/journals) for reversal mechanics.

## Step 3 — Review trends before locking

Numbers can balance and still be wrong. Before closing, review monthly trends (**Budgeting → Trend**, REVENUE and EXPENSE views):

- revenue or expense lines that jump versus prior months,
- accounts moving in the wrong direction (normal-balance aware — an expense account behaving like a credit),
- budget vs actual variance (Budgeting → Vs-Actual) for the month being closed.

Anomalies found here are corrected with **reversals** — never edits — keeping the audit trail intact.

## Step 4 — The period is closed. And that means closed.

When a fiscal period is closed, new transactions dated inside it are rejected by the engine:

- `PERIOD_NOT_FOUND` or a period-status check fires inside the RPC — not a UI convention, but the `fiscal_periods` table itself.
- No role can override it, including SUPER_ADMIN. If something truly must be booked into a closed month, post it into the open period where it belongs.

This is what makes the trial balance you certified in step 2 durable: the number cannot drift after the fact.

## The close, as a checklist

1. ☐ Payroll approved + disbursed for the month
2. ☐ Depreciation batch run for the month
3. ☐ POS batch journals posted
4. ☐ All sales / procurement invoices posted
5. ☐ Trial balance as-of month-end → `is_balanced: true`
6. ☐ Trends reviewed, anomalies reversed
7. ☐ Period closed — engine now rejects backdated posting

## What's next

- [Daily Journal Entry](/docs/journals) — the flow this close certifies.
- [Procure-to-Pay](/docs/procure-to-pay) and [Order-to-Cash](/docs/order-to-cash) — the source flows from step 1.
- Deep-dive: `docs/USER_FLOWS.md` §3 in the repository.
