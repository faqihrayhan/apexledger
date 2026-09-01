# Daily Journal Entry (GL)

The general ledger is the heart of ApexLedger: every other module — sales, purchasing, payroll, assets, POS — ends its flow by posting a journal here. This page walks a journal through its whole life: chart of accounts → draft → post → reverse → verify.

**Actors:** any accounting role — FINANCE_OPERATOR and above.

## Before you start: the chart of accounts

Nothing can post before accounts exist. Create them on the **Accounts** page (`POST /gl/accounts`):

- **Account codes are unique per entity** — two entities can both have `1000 Cash`, one entity cannot have it twice.
- Accounts with posting history cannot be deleted — soft-delete only. The ledger's integrity outranks tidiness.

A starter chart for a small Indonesian company: `1000 Cash`, `1100 Bank`, `2100 Accounts Payable`, `4000 Revenue`, `5000 Expenses`.

## Draft the entry

On the **New Journal** page:

1. Pick a **date** — it determines the fiscal period the entry posts into.
2. Add lines: account, debit or credit, description.
3. Watch the **live balance meter** — debits and credits are summed in **BigInt cents math**, and the submit button stays disabled until both sides are equal.

The meter is UX, not security. When you hit submit, `POST /gl/journal-entries` re-validates the balance **inside PostgreSQL** — a hand-crafted API call with a one-rupiah imbalance is rejected by the engine, not by your browser.

Why BigInt cents? Money travels as strings (Decimal precision) and the engine computes in `NUMERIC` — floating-point rounding bugs are structurally impossible, not just rare.

## Post it

From the Journals list, hit **Post**. `fn_post_journal_entry` flips `DRAFT → POSTED` and, in the same transaction, assigns the official number `JE-YYYYMM-NNNNN` from a per-entity sequence.

Two things happen on post:

- The entry becomes **immutable** — no `UPDATE` or `DELETE` grants exist on `journal_entries` at the database level. Not "hidden in the UI" — the grants do not exist.
- The fiscal period is checked — posting into a closed period is rejected by the engine (`PERIOD_NOT_FOUND` or the period-status check).

## Correct a mistake

Never edit a posted entry — you can't. Issue a **reversal** instead (`POST /gl/journal-entries/{id}/reverse`):

1. The engine creates a **mirrored entry** — same lines, debits and credits inverted.
2. It is linked back to the original; the original's status becomes `REVERSED`.
3. If needed, post a fresh corrected entry as usual.

The audit trail stays complete: original, reversal, correction — three entries, zero mysteries.

## Verify: the trial balance

The Trial Balance page (`POST /gl/reports/trial-balance`) shows net debit/credit per account:

- **as-of date filtering** — balance the book at any historical cut-off,
- **`is_balanced` proof** — grand totals must match; if the flag says true, the ledger is mathematically sound.

Run it before every month-end close — see [Month-End Close](/docs/month-end-close).

## Guards recap

| Guarantee | Enforced by |
|---|---|
| Balanced entries only | RPC re-validation → `JE_UNBALANCED` |
| Unique account codes per entity | DB constraint + RPC |
| Posted = immutable | no UPDATE/DELETE grants on `journal_entries` |
| Closed periods reject posting | fiscal_periods status checks |
| Role + entity scoping | API guards + NULL-hardened RPC checks |

## What's next

- [Month-End Close](/docs/month-end-close) — turning daily entries into a closed period.
- [Order-to-Cash](/docs/order-to-cash) and [Procure-to-Pay](/docs/procure-to-pay) — the flows that feed this ledger.
- Deep-dive: `docs/USER_FLOWS.md` §2 in the repository.
