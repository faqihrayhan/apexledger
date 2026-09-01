# Roles

ApexLedger ships **nine roles** in three tiers — board/admin, department heads, and operators. Roles are assigned at user creation, checked on every write, and cannot be escalated from inside the app.

## The nine roles

| Tier | Role | Typical duties |
|---|---|---|
| Admin | `SUPER_ADMIN` | everything — incl. locking budgets, revising locked budgets |
| Board | `DIREKSI` | board-level approval for high-value POs and kasbons (via thresholds) |
| Dept head | `DEPT_HEAD_FA` | finance authority: budget create/approve/revise, asset disposal, kasbon disburse/settle |
| Dept head | `DEPT_HEAD_SALES` | sales authority: SO confirmation, customer master |
| Dept head | `DEPT_HEAD_WAREHOUSE` | warehouse authority: GRN, transfers, work orders |
| Operator | `FINANCE_OPERATOR` | day-to-day finance: journals, invoices, payments, payroll calculate, asset register/depreciation |
| Operator | `SALES_OPERATOR` | SO entry, POS sales |
| Operator | `WAREHOUSE_OPERATOR` | receiving, issuing, delivery orders |
| Infrastructure | `IT_ADMIN` | infrastructure, read-only forecast access |

A small team can start with one SUPER_ADMIN and one FINANCE_OPERATOR; the nine roles exist so a growing company never needs to share logins.

## Every check runs twice

Role enforcement is **layered**, not single-door:

1. **Coarse guards at the API layer** — the FastAPI wrapper rejects requests whose JWT lacks the required role claim before any business logic runs.
2. **NULL-hardened checks inside the PL/pgSQL RPCs** — the engine re-verifies the role inside PostgreSQL, where a missing claim is treated as **no permission** and rejected outright.

All **30 role-guarded RPCs** behave this way, and the behavior is **locked by regression tests** — a refactor cannot silently turn a missing claim into "allow". There is no UI-only security: hiding a button is cosmetic; the engine is the lock.

## Approval authority is dynamic — data, not code

Who must approve a purchase order or a kasbon is not hardcoded. `fn_get_required_approval_role` reads the `approval_thresholds` table (ordered by `min_amount` DESC) and stamps the required role onto the document:

```
amount 500,000    → may auto-approve
amount 250,000,000 → may require DIREKSI
```

(tune the exact brackets in your own `approval_thresholds` data.)

Two consequences:

- **Your finance team changes approval policy by editing data** — no migration, no deploy, no developer.
- **A user below the required role gets `INSUFFICIENT_APPROVAL_AUTHORITY`** from the RPC itself — e.g. a FINANCE_OPERATOR trying to approve a DIREKSI-level kasbon.

## Assigning roles

- Users are created via `POST /api/v1/auth/register` (authenticated) with an explicit role — the first SUPER_ADMIN comes from the [setup wizard](/docs/first-boot).
- Once the instance is initialized, every registration **requires an `entity_id`** — no orphan users outside your company.
- The role travels in the JWT; the [AI assistant](/docs/configuration) is subject to the same role scoping as its logged-in user.

## What's next

- [First-Boot Setup](/docs/first-boot) — creating the first users.
- [Procure-to-Pay](/docs/procure-to-pay) — the threshold engine in action.
- Deep-dive: `docs/USER_FLOWS.md` → Role Reference in the repository.
