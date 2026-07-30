# E6 — Payments

Select bills, authorize once, watch the stages, handle what goes wrong.

← [Index](README.md) · Prev: [E5](e5-banking.md) · Next: [E7 AI Advisor](e7-ai-advisor.md)

---

## 1. Four things to know first

### 1.1 Creating a payment does not move money

`POST /payments/` only **reserves** the work and returns text to display.
Nothing leaves the account until `confirm/`. Two steps, always.

### 1.2 One authorization covers a batch

Selecting six bills produces six payments and **one** `PaymentBatch`. The user
consents once, on the batch — not six times.

So **confirm the batch, not the payments.** Confirming a batched payment
individually returns 400 telling you so.

### 1.3 Swayp never holds the money ⚠️

A hard product invariant, not an implementation detail. Funds move directly
from the user's bank to the vendor via a licensed provider. There is no Swayp
balance, no top-up, no wallet — that subsystem was deleted and its routes 404.

**Never build a "balance" UI**, and never show a processor name anywhere
except inside the authorization text, where NACHA requires it.

### 1.4 A retry is a new payment

Resolving a failure never revives the failed payment. It creates a **new** one
against the same bill, linked by `replaced_payment_id`. The failed one stays
`FAILED` forever, which is what makes the history readable.

---

## 2. The pay flow

```
POST /payments/                        → payments + authorization_text
   ↓  display the text, get acceptance
POST /payments/batches/<id>/confirm/   → authorized, execution starts
   ↓
GET  /payments/batches/<id>/status/    → poll until in_flight is 0
   ↓
GET  /payments/<id>/                   → receipt
```

### Step 1 — create

```
POST /api/v1/payments/
```

```json
{ "occurrence_ids": ["e200c2f4-…", "71e76f76-…"],
  "funding_account_id": "optional — defaults to the funding source",
  "rail": "ACH_STANDARD",
  "scheduled_for": "optional — YYYY-MM-DD, future-dates the send",
  "expedited": "optional — CHECK rail only, $8.99" }
```

**201:**

```json
{ "batch_id": "38ed6ea5-…",
  "payments": [
    { "id": "febd4a55-…", "transaction_reference": "SWP-20260728-0001",
      "status": "PENDING", "amount": "3200.00", "fee": "0.00",
      "total": "3200.00", "currency": "USD", "rail": "ACH_STANDARD",
      "vendor_name": "WeWork",
      "funding_account": "Chase Business Checking ****4821",
      "initiated_date": "2026-08-28", "estimated_arrival": "2026-09-01",
      "cancellation_deadline": "2026-08-29T03:59:00Z",
      "scheduled_for": null, "expedited": false } ],
  "authorization_text": "I authorize Swayp to debit Chase Business Checking ****4821 …",
  "total": "6400.00" }
```

`batch_id` is **`null`** for a single payment — that is the signal to use the
single-payment confirm endpoint instead.

**`authorization_text` must be displayed verbatim.** Do not summarise, reflow
or translate it: it is stored as the record of what the user agreed to, and it
names the licensed provider because NACHA requires it.

The selected occurrences become `SCHEDULED`, which is what stops reminders.

**Rails:** `ACH_STANDARD` (free) · `ACH_SAMEDAY` ($4.99) · `NETWORK` ·
`CHECK` (free to the plan allotment, then $2.99; `expedited: true` = $8.99).
Fees are [E9](e9-billing.md).

⚠️ **Hide same-day after the daily cutoff** (11:59 PM Eastern). Past it the
rail cannot deliver, so it is withdrawn rather than sold — no fee, no row.

⚠️ **`expedited` is CHECK-only.** On any other rail it is a 400, not a silent
downgrade. It cuts check transit from 5 business days to 2.

**400s worth handling:**

| Cause | Message |
|---|---|
| Already in flight | `"A payment is already in flight for 1 of these bills."` |
| Already paid | `"Already paid: …"` |
| No bank connected | `"No funding account is available. Connect a bank account first."` |

### Step 2 — confirm

```
POST /api/v1/payments/batches/<batch_id>/confirm/
POST /api/v1/payments/<payment_id>/confirm/        ← only when batch_id was null
```

```json
{ "authorization_text": "…the exact text you displayed…" }
```

Send it back **verbatim**. Re-confirming **replays** rather than recording a
second consent, and the response carries `"replayed": true`.

⚠️ **Needs the `send_money` capability.** A MEMBER gets **403** here — they can
prepare a payment but not authorize it. See [E10](e10-teams.md).

### Step 3 — poll

```
GET /api/v1/payments/batches/<batch_id>/status/
GET /api/v1/payments/<payment_id>/status/
```

Returns an ordered stage checklist plus `progress`. Poll while the drawer is
open; stop when `in_flight` reaches 0.

### Step 4 — receipt

```
GET /api/v1/payments/<payment_id>/
```

Full detail with `stages`, `receipt`, `failure` and `progress`.

---

## 3. Cancelling

```
POST /api/v1/payments/<payment_id>/cancel/
POST /api/v1/payments/batches/<batch_id>/cancel/
```

Allowed **until `cancellation_deadline`**, including while the payment is
`PROCESSING` — ACH can be pulled back before it settles, and Swayp voids it at
the processor too. Past the deadline it is a **409**.

⚠️ **`cancellation_deadline` is UTC on the wire, Eastern in meaning.**

```json
"cancellation_deadline": "2026-08-29T03:59:00Z"
```

That is 11:59 PM Eastern on **August 28**. Render it in `America/New_York` or
a user in California is told the wrong hour. See [E1](e1-foundations.md).

---

## 4. Failure recovery

```
GET  /api/v1/payments/<payment_id>/failure/
POST /api/v1/payments/<payment_id>/resolve/
```

`failure/` returns a human explanation and the actions available. It is a
**400 on a healthy payment** — there is no failure to report.

```json
{ "action": "RETRY", "payment_method_id": "optional",
  "funding_account_id": "optional", "scheduled_for": "optional" }
```

Resolving creates a **new** payment (see §1.4). Read `replaced_payment_id` on
the result to link the two in the history.

---

## 5. History

```
GET /api/v1/payments/history/?status=&providerId=&categoryId=&page=1
```

`data` + `pagination` at the top level. `providerId`, `providerName`,
`categoryId` and `categoryName` can each be **`null`** — render a dash, not
an empty string.

---

## 6. Webhooks and the states you'll see

Processors call Swayp; you never call these. What matters to you is that
**status can change without a user action**, so refetch on focus.

| Status | Terminal? |
|---|---|
| `SCHEDULED` → `PENDING` → `PROCESSING` | no |
| `SUCCESSFUL` | can still become `RETURNED` or `REFUNDED` |
| `FAILED`, `CANCELLED`, `RETURNED`, `REFUNDED` | yes |

⚠️ **A late ACH return can take a `SUCCESSFUL` payment to `RETURNED` days
later**, and the occurrence goes back to unpaid. Don't cache "paid" forever.

**`SUCCESSFUL` is not "arrived".** The processor accepted it; a check is still
five business days from the letterbox. `estimated_arrival` is the arrival
date, and it is what the delivery guarantee is measured against
([E9](e9-billing.md)).

---

## 7. Staff-only routes

`PATCH /payments/<id>/processing|successful|failed/` return **403**. These
transitions are internal and driven by webhooks. Nothing in the product should
call them.

---

## 8. Order to build

1. **Create + display authorization text** — get the consent step right first.
2. **Confirm** (batch and single).
3. **Status polling** with the stage checklist.
4. **Receipt.**
5. **Cancel**, with the Eastern deadline rendered correctly.
6. **Failure + resolve** — last, and the most fiddly.
