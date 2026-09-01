# Procure-to-Pay (M5)

From vendor master to the final payment, procurement in ApexLedger is one auditable pipeline: PO → approval → receiving → inspection → 3-way match → payment. Every state change is a guarded RPC, and goods never touch stock un-inspected.

**Actors:** FINANCE_OPERATOR (creates PO), the dynamic approval role, WAREHOUSE_OPERATOR (receives), finance (bill + payment).

## 1. Vendor master

Procurement → Vendors: add each vendor with **payment terms (days)** and **NPWP**. The terms drive every bill's due date later — set them right at creation.

## 2. Purchase order

Create the PO with lines (item, qty, unit price). Status: `DRAFT` — nothing is committed, no stock is promised.

## 3. Submit — the dynamic approval engine

`fn_submit_purchase_order` reads the `approval_thresholds` table (ordered by min_amount DESC) and **stamps the required role onto the PO**:

- small values may **auto-approve**,
- large values can require **DIREKSI** (board level).

The requirement is data, not code — your finance team tunes thresholds without touching a migration. Status → `PENDING_APPROVAL`.

## 4. Approve

A user **at or above** the stamped role approves. A weaker role gets `INSUFFICIENT_APPROVAL_AUTHORITY` straight from the RPC — the UI hides nothing, the engine enforces everything. Status → `APPROVED`.

## 5. Receive goods — nothing enters stock yet

The WAREHOUSE_OPERATOR records a **Goods Received Note (GRN)** per PO. Stock is **not** booked at this point — the quantity sits as **PUTG (Pending Untested Goods)**. Status → `PARTIALLY_RECEIVED` / `RECEIVED`.

This is deliberate: un-inspected goods are not inventory. A damaged shipment never contaminates your on-hand quantities or costs.

## 6. Inspect (PUTG)

Per GRN line, enter **accepted vs rejected** quantities:

- **Accepted** — flows into stock at PO price via `fn_receive_stock`; the GL posts Dr Inventory / Cr GR-IR clearing.
- **Rejected** — never enters stock.

GRN status → `PASSED` / `PARTIAL` / `REJECTED`.

## 7. AP bill

Finance creates a bill from a `PASSED`/`PARTIAL` GRN — **one bill per GRN**. Due date = bill date + the vendor's payment terms from step 1.

## 8. The 3-way match

`fn_match_and_approve_ap_bill` compares **three documents**:

| Document | Field |
|---|---|
| Bill | qty, price |
| GRN | accepted qty |
| PO | price (±2% tolerance) |

- **Mismatch** → status `DISPUTED` with a machine-written reason, **no GL posting**. The bill does not become payables until a human resolves it.
- **Match** → GL posts Dr GR-IR + Dr PPN Masukan + price variance / Cr AP.

## 9. Pay

`fn_record_ap_payment` posts Dr AP / Cr cash-bank and **allocates FIFO by due date** — oldest bills get the money first. Bill → `PAID`.

## Side flows

| Flow | What happens |
|---|---|
| **Purchase return** | debit note; stock out **at cost basis**; Dr AP / Cr Inventory / Cr PPN |
| **Landed cost** | capitalize freight/customs into item cost, allocated by **qty / value / weight** |

## Guards recap

| Guard | Fires when |
|---|---|
| `PO_INVALID_STATUS` | receiving before approval |
| `RECEIPT_EXCEEDS_ORDER` | over-receipt |
| `GRN_NOT_INSPECTED` | billing an un-inspected GRN |
| status guards | double inspection, double billing |

## What's next

- [Order-to-Cash](/docs/order-to-cash) — the mirror flow on the sales side.
- [Month-End Close](/docs/month-end-close) — where these invoices land at close.
- Deep-dive: `docs/USER_FLOWS.md` §4 in the repository.
