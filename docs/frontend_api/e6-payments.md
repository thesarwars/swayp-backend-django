# E6 — Payments

Select bills, authorize once, watch the stages, handle what goes wrong.

← [Index](README.md) · Prev: [E5](e5-banking.md) · Next: [E7 AI Advisor](e7-ai-advisor.md)

---

## 1. Four things to know first

### 1.1 Creating a payment does not move money

`POST /payments/` only **reserves** the work and returns text to display.
Nothing leaves the account until `confirm/`. Two steps, always.

The reservation marks the bill occurrence `SCHEDULED` at once, so reminders
stop. **An unconfirmed payment lapses after 30 minutes**: it is cancelled and
its bill is released. `GET payments/<id>` shows the time as `confirm_by`. If
the user comes back after that, create a new payment. An unconfirmed payment
can also be cancelled at any time (§3), so a "Back" from the confirm screen
should cancel it.

`GET payments/<id>` says where an interrupted flow stands:

| Field | Meaning |
|---|---|
| `authorized_at` | When it was confirmed. `null` means not confirmed yet. |
| `authorization_text` | The text the user agreed to, or `null` before that. |
| `confirm_by` | When an unconfirmed payment lapses. `null` once confirmed or finished. |

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
POST /payments/batches/<id>/confirm   → authorized, execution starts
   ↓
GET  /payments/batches/<id>/status    → poll until in_flight is 0
   ↓
GET  /payments/<id>                   → receipt
```

### Step 1 — create

```
POST /api/v1/payments
```

```json
{ "occurrence_ids": ["e200c2f4-…", "71e76f76-…"],
  "funding_account_id": "optional — defaults to the funding source",
  "rail": "optional — omitted means each bill's own rail",
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
      "vendor_id": "0ec2bf6c-…", "vendor_name": "WeWork",
      "funding_account": "Chase Business Checking ****4821",
      "funding_account_id": "a91…", "bill_id": "d788620d-…",
      "bill_occurrence": "e200c2f4-…", "payment_method_id": "5c2e…",
      "initiated_date": "2026-08-28", "estimated_arrival": "2026-09-01",
      "cancellation_deadline": "2026-08-29T03:59:00Z",
      "scheduled_for": null, "expedited": false } ],
  "authorization_text": "I authorize Swayp to debit Chase Business Checking ****4821 …",
  "total": "6400.00" }
```

`batch_id` is **`null`** for a single payment — that is the signal to use the
single-payment confirm endpoint instead.

Every payment body (create, detail, status, cancel, resolve) carries
`vendor_id`, `bill_id`, `bill_occurrence` (the occurrence id),
`funding_account_id` and `payment_method_id` (the bill's saved method, which
the money goes to). Use them to go from a payment to its bill or vendor. For
a deep link that carries only an occurrence id, `GET
bills/occurrences/<id>` returns that one row, in the same shape as the list.

**`authorization_text` must be displayed verbatim.** Do not summarise, reflow
or translate it: it is stored as the record of what the user agreed to, and it
names the licensed provider because NACHA requires it.

The selected occurrences become `SCHEDULED`, which is what stops reminders.

**Rails:** `ACH_STANDARD` (free) · `ACH_SAMEDAY` ($4.99) · `NETWORK` ·
`CHECK` (free to the plan allotment, then $2.99; `expedited: true` = $8.99).
Fees are [E9](e9-billing.md). An account with no plan is charged no fees.

**Omit `rail` and each bill uses its own**, the rail its saved payment
method implies: an ACH account → `ACH_STANDARD`, a check address → `CHECK`, a
network payee → `NETWORK`. This is the same rule autopay uses, and a batch can
then mix rails. It used to be `ACH_STANDARD` for everything. **An explicit
`rail` has to suit the method**, because the money goes there: an ACH account
takes `ACH_STANDARD` or `ACH_SAMEDAY`, a check address takes `CHECK`, a network
payee takes `NETWORK`. Anything else is a 400 on `errors.rail`.

### Quote first

Ask what each rail costs and when it lands before creating anything:

```
POST /api/v1/payments/quote   { "occurrence_ids": ["…"], "scheduled_for": null }
```

```json
{ "occurrences": [
    { "occurrence_id": "e200c2f4-…", "default_rail": "ACH_STANDARD",
      "rails": [
        { "rail": "ACH_STANDARD", "available": true, "unavailable_reason": null,
          "fee": "0.00", "initiated_date": "2026-08-28",
          "estimated_arrival": "2026-09-01", "expedited": null },
        { "rail": "ACH_SAMEDAY", "available": false,
          "unavailable_reason": "Past today's same-day cutoff.", "fee": "4.99", "…": "…" },
        { "rail": "CHECK", "available": false,
          "unavailable_reason": "This vendor is paid by ACH.", "fee": "0.00",
          "expedited": { "fee": "8.99", "estimated_arrival": "2026-08-31" }, "…": "…" }
      ] } ] }
```

Show only `available` rails, with their fee and arrival date. `default_rail`
is what create uses when `rail` is omitted. The quote handles the same-day
cutoff (11:59 PM Eastern) for you, so there is no time-zone maths on the
client. Check fees count down the plan's free checks across the quote,
assuming every quoted check is sent. Nothing is created or charged.

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
POST /api/v1/payments/batches/<batch_id>/confirm
POST /api/v1/payments/<payment_id>/confirm        ← only when batch_id was null
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
GET /api/v1/payments/batches/<batch_id>/status
GET /api/v1/payments/<payment_id>/status
```

Returns an ordered stage checklist plus `progress`. Poll while the drawer is
open; stop when `in_flight` reaches 0.

### Step 4 — receipt

```
GET /api/v1/payments/<payment_id>
```

Full detail with `stages`, `receipt`, `failure` and `progress`.

For "Download Receipt", fetch the PDF:

```
GET /api/v1/payments/<payment_id>/receipt.pdf
```

It is `application/pdf`, sent as a download named
`swayp-receipt-<reference>.pdf`, with the reference, payee, date, account,
method, amount, fee and total. It is only available once the payment has
completed (`SUCCESSFUL`); before that it is a **409**. Send the usual
`Authorization` header; it is not a public link.

---

### Changing the date before confirming

```
PATCH /api/v1/payments/<payment_id>     { "scheduled_for": "2026-09-20" }
```

Moves an **unconfirmed** payment to another date in place: same payment, same
reference, and the bill stays reserved. The start, arrival and cancellation
dates are recomputed, and the answer is the payment detail. `null` makes it
pay now again. The date must be today or later. Weekends and holidays are
accepted, because dates are counted from it in business days. A confirmed
payment is a 400: its date was part of what the user authorized, so cancel
it and create a new one.

## 3. Cancelling

```
POST /api/v1/payments/<payment_id>/cancel
POST /api/v1/payments/batches/<batch_id>/cancel
```

Allowed **until `cancellation_deadline`**, including while the payment is
`PROCESSING` — ACH can be pulled back before it settles, and Swayp voids it at
the processor too. Past the deadline it is a **409**.

**The deadline only applies once the payment is confirmed.** An unconfirmed
payment has authorized nothing, so it can be cancelled at any time. (For pay
now, the deadline has already passed when the payment is created, so before
this rule an abandoned one could never be cancelled.)

⚠️ **`cancellation_deadline` is UTC on the wire, Eastern in meaning.**

```json
"cancellation_deadline": "2026-08-29T03:59:00Z"
```

That is 11:59 PM Eastern on **August 28**. Render it in `America/New_York` or
a user in California is told the wrong hour. See [E1](e1-foundations.md).

---

## 4. Failure recovery

```
GET  /api/v1/payments/<payment_id>/failure
POST /api/v1/payments/<payment_id>/resolve
```

`failure/` is a **400 on a healthy payment** — there is no failure to report.
Otherwise:

```json
{ "payment_id": "…", "transaction_reference": "SWP-…",
  "title": "Not enough money in the account",
  "explanation": "Your bank declined the debit because the account didn't have enough funds at the time. …",
  "amount": "3200.01", "vendor_name": "WeWork", "failed_at": "…",
  "failure_reason": "NSF", "failure_detail": { "balance": "1200.00" },
  "due_date": "2026-09-01", "days_overdue": 3,
  "late_fee": { "amount": "50.00", "grace_days": 5, "days_remaining": 2, "applies": false },
  "available_actions": ["retry", "change_method", "reschedule"] }
```

Show `title` and `explanation` as they are; don't map `failure_reason`
codes yourself. `late_fee` is `null` when the vendor has no late fee.

```json
{ "action": "retry", "payment_method_id": "optional",
  "funding_account_id": "optional", "scheduled_for": "optional" }
```

**`action` is lowercase:** `retry`, `change_method` or `reschedule`.
`change_method` needs `payment_method_id` and moves to that method's rail
(for example to `CHECK`). `reschedule` needs `scheduled_for`.

Resolving creates a **new, unconfirmed** payment (see §1.4). The **201**
answer:

```json
{ "action": "retry", "payment": { "id": "…", "…": "…" },
  "replaced_payment_id": "…",
  "authorization_text": "I authorize Swayp to debit …",
  "requires_confirmation": true }
```

Show `authorization_text`, then `POST payments/<payment.id>/confirm` with it,
exactly as in step 2. Like any unconfirmed payment, it lapses after 30
minutes (§1.1). `replaced_payment_id` links the two in the history.

---

## 5. History

```
GET /api/v1/payments/history?status=&providerId=&categoryId=&page=1
```

`data` + `pagination` at the top level. `providerId`, `providerName`,
`categoryId` and `categoryName` can each be **`null`** — render a dash, not
an empty string.

**Show `vendorName` as the recipient, not `providerName`.** `providerName` is
the biller-directory provider, which a payment to one of the user's own
vendors does not have, so it is usually `null` for bill payments. Each row
also carries:

| Field | Meaning |
|---|---|
| `vendorId`, `vendorName` | Who was paid |
| `billId`, `occurrenceId` | The bill and due date it paid; `null` if none |
| `rail` | `ACH_STANDARD`, `ACH_SAMEDAY`, `CHECK` or `NETWORK` |
| `estimatedArrival`, `scheduledFor` | Dates, or `null` |
| `replacedPaymentId` | The failed payment this one retried, or `null` |

History rows stay **camelCase**, unlike the other payment bodies. Changing it
would break current clients.

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

## 7b. Testing against the mock processor

On dev and staging, payments go through a mock processor that picks the
outcome from the **cents of the amount**, so QA can reach each screen without
patching anything:

| Amount ends in | Outcome |
|---|---|
| `.01` (e.g. `3200.01`) | **Fails with `NSF`** (insufficient funds): the failure screen, with `failure_detail.available_balance` set. Resolve it from there. |
| `.02` | **Lost response**: the transfer is sent, then the call errors. The payment stays `PROCESSING` until the hourly reconcile finds it, about 30 minutes later, and completes it. Use it to test a payment that stays in "Processing". |
| anything else | **Succeeds** at once, with every stage `DONE`. |

Set the amount on the bill or occurrence before paying. There is no
"slow but successful" amount yet; `.02` is the nearest.

## 8. Order to build

1. **Create + display authorization text** — get the consent step right first.
2. **Confirm** (batch and single).
3. **Status polling** with the stage checklist.
4. **Receipt.**
5. **Cancel**, with the Eastern deadline rendered correctly.
6. **Failure + resolve** — last, and the most fiddly.
