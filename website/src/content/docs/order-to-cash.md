# Order-to-Cash (M4)

The mirror of [Procure-to-Pay](/docs/procure-to-pay) on the sales side: customer → order → delivery → invoice → payment. Two things make this flow safe — the **credit gate** runs before confirmation, not after delivery, and **COGS is booked per item at real cost**, never at guesswork.

**Actors:** SALES_OPERATOR (orders), WAREHOUSE_OPERATOR (delivery), FINANCE_OPERATOR (invoice/payment).

## 1. Customer master

Set each customer's **credit limit**, **payment terms (days)**, and NPWP. The credit limit is enforced in step 3; the terms drive invoice due dates.

## 2. Sales order

Create the SO with lines (qty & price). Status: `DRAFT` — no stock reserved, nothing committed.

## 3. Confirm — the credit gate

`fn_check_credit_limit` runs **before** confirmation, inside the RPC:

```
outstanding AR + open orders + this order  vs.  the customer's limit
```

- **Exceeded** → `CREDIT_LIMIT_EXCEEDED`, the SO stays `DRAFT`. No exception path — an operator cannot "force it through".
- **Passed** → `CONFIRMED`.

Because the check runs at confirmation, a customer over their limit can never accumulate more deliverable orders — the gate is at the door, not at the exit.

## 4. Delivery order

The warehouse issues stock per line at **moving-average cost**:

- **Partial deliveries allowed** → `PARTIALLY_DELIVERED` → `DELIVERED`.
- **Over-delivery is blocked** — you cannot ship more than the confirmed order.
- Stock availability is checked before any cost layer is burned — no negative stock.

## 5. AR invoice

Issued from a delivery order (3-way match **DO ↔ SO**). PPN **11%** by default. The GL posting is two-sided and per item:

```
Dr  AR                    (revenue + PPN)
Cr  Revenue
Cr  PPN Keluaran
```

```
Dr  COGS          ┐ per item — the moving-average cost
Cr  Inventory     ┘ from the delivery, not the sale price
```

The COGS entry per item is what makes gross margin on any report truthful.

## 6. Payment

`fn_record_ar_payment` **auto-allocates FIFO by due date** (or an explicit allocation if you prefer):

- posts Dr Cash / Cr AR,
- a **surplus stays unallocated** on the invoice — overpayment never silently becomes revenue,
- fully-paid invoice → `PAID`.

## 7. Returns

A sales return takes stock back **at cost basis** — never at sale price:

- issues a credit note: Dr Sales Return / Dr PPN / Cr AR + Dr Inventory / Cr COGS,
- reduces the customer's AR balance.

Because stock returns at cost, a returned item re-enters inventory at what it cost you — a high-margin product cannot inflate your inventory value on the way back in.

## Guards recap

| Guard | Fires when |
|---|---|
| `CREDIT_LIMIT_EXCEEDED` | order would push the customer over their limit |
| `SO_INVALID_STATUS` | delivering a DRAFT sales order |
| `DO_ALREADY_INVOICED` | double invoicing a delivery order |
| `RETURN_QTY_EXCEEDS_INVOICE` | returning more than was invoiced |

## What's next

- [Procure-to-Pay](/docs/procure-to-pay) — the mirror flow on the buying side.
- [Month-End Close](/docs/month-end-close) — where these invoices land at close.
- Deep-dive: `docs/USER_FLOWS.md` §5 in the repository.
