# First-Boot Setup

A fresh ApexLedger database is empty on purpose: no users, no entity, no fiscal calendar. On first visit the login form is replaced by the **Setup Wizard**, which creates everything in one shot.

## How the wizard appears

The frontend calls `GET /api/v1/system/status` on the login page. A fresh database answers `is_initialized: false`, and the wizard is rendered instead of the login form. You cannot miss it — there is no way to log in before setup, and no way to see the wizard after.

## Fill the wizard

| Field | Meaning | Constraints |
|---|---|---|
| Entity code + name | your company identity | code 2–20 chars, unique |
| Base currency | the ledger's default currency | default `IDR` |
| Admin full name / email / password | the first user | password ≥ 8 chars |
| Fiscal year | the year your ledger starts | e.g. `2026`, range 2000–2100 |

## What happens on submit

`POST /api/v1/system/setup` runs **one atomic transaction** — either everything is created or nothing is:

1. **Entity** — the company record everything else hangs off.
2. **SUPER_ADMIN user** — you, with the highest of the nine roles.
3. **Fiscal year** — plus its **12 monthly periods**, so day-one transactions are postable immediately.
4. **Audit log entry** — the very first audit record marks the instance as initialized.

The response returns the first `access_token` — you land straight inside the app, already logged in. No separate "now log in" step.

## Guards

- Setup is **once-only**. A second call to the endpoint is rejected by the engine, no matter who asks.
- Once the instance is initialized, every user registration **requires an `entity_id`** — you cannot create orphan users outside your entity.

## Adding your team

Users are created via `POST /api/v1/auth/register` (authenticated) after setup:

- Pick one of the **nine roles** — from SALES_OPERATOR up to SUPER_ADMIN (see [Roles](/docs/roles)).
- Role checks run **twice**: coarse guards at the API layer, and NULL-hardened checks inside the PL/pgSQL RPCs — a missing role claim is rejected outright, not just hidden in the UI.
- New users log in with their own credentials; there is no shared password.

A typical small team: one SUPER_ADMIN (you), one FINANCE_OPERATOR, and one or two module operators (SALES_OPERATOR, WAREHOUSE_OPERATOR).

## What's next

- [Daily Journal Entry](/docs/journals) — your first balanced journal, draft to posted.
- [Configuration](/docs/configuration) — environment variables and the AI modes.
- The full role-by-role matrix lives in [Roles](/docs/roles).
