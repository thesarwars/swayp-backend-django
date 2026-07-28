# Payments API Documentation

The pay flow: select bills, authorize once, watch the stages, and handle what
happens when it goes wrong.

**Base URL:** `/api/v1/payments/` · **Webhooks:** `/webhooks/` (versionless)
**Auth:** every payment endpoint requires `Authorization: Bearer <access_token>`.

Every response body below was captured from the running API.

Related: [Bills API](bills-api-documentation.md) · [Banking API](banking-api-documentation.md) · [Frontend Guide](frontend-integration-guide.md)

---

## 1. Read this first

### 1.1 Creating a payment does not move money

`POST /payments/` only **reserves** the work and returns text to display.
Nothing leaves the account until `confirm/` is called. Two steps, always.

### 1.2 One authorization covers a batch

Selecting six bills produces six payments and **one** `PaymentBatch`. The user
consents once, on the batch — not six times.

So: **confirm the batch, not the payments.** Confirming a batched payment
individually returns 400 telling you so.

### 1.3 Swayp never holds the money ⚠️

This is a hard product invariant, not an implementation detail. Funds move
directly from the user's bank to the vendor via a licensed provider (Moov for
ACH, Stripe for network, Lob for checks). There is no Swayp balance, no
top-up, no wallet — the stored-balance subsystem was **deleted**.

Practically: never build a "balance" UI, and never show a processor name
anywhere except inside the authorization text where NACHA requires it.

### 1.4 `cancellation_deadline` is UTC on the wire, Eastern in meaning

```json
"cancellation_deadline": "2026-08-29T03:59:00Z"
```

That is **11:59 PM Eastern on August 28** serialized as UTC. The promise is a
wall clock — "cancel before 11:59 PM today" — and it holds across DST because
the server stores it as an aware Eastern datetime.

**Render it in `America/New_York`, not the device's timezone**, or a user in
California will be told the wrong hour.

### 1.5 A retry is a new payment

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

### Step 1 — Create

```
POST /api/v1/payments/
```

```json
{ "occurrence_ids": ["e200c2f4-…", "71e76f76-…"],
  "funding_account_id": "optional — defaults to the funding source",
  "rail": "ACH_STANDARD",
  "scheduled_for": "optional — YYYY-MM-DD, future-dates the send" }
```

**201:**

```json
{
  "success": true,
  "message": "Payments created. Confirm to authorize.",
  "data": {
    "batch_id": "38ed6ea5-…",
    "payments": [
      { "id": "febd4a55-…", "transaction_reference": "SWP-20260728-0001",
        "status": "PENDING", "amount": "3200.00", "fee": "0.00",
        "total": "3200.00", "currency": "USD", "rail": "ACH_STANDARD",
        "vendor_name": "WeWork",
        "funding_account": "Chase Business Checking ****4821",
        "bill_occurrence": "e200c2f4-…", "batch": "38ed6ea5-…",
        "initiated_date": "2026-08-28", "estimated_arrival": "2026-09-01",
        "cancellation_deadline": "2026-08-29T03:59:00Z",
        "scheduled_for": null, "created_at": "2026-07-28T13:07:12.729164Z" }
    ],
    "authorization_text": "I authorize Swayp to debit Chase Business Checking ****4821 for a total of $6,400.00 covering 2 bills. These transfers will be executed by Moov Financial, Inc. I understand this authorization covers every payment listed above and remains in effect until they complete or I cancel them.",
    "total": "6400.00"
  }
}
```

`batch_id` is **`null`** for a single payment — that is the signal to use the
single-payment confirm endpoint instead.

**`authorization_text` must be displayed verbatim.** Do not summarise, reflow
or translate it: it is stored as the record of what the user agreed to, and it
names the licensed provider because NACHA requires it.

The selected occurrences become `SCHEDULED`, which is what stops bill
reminders.

Dates come from the business-day engine — `initiated_date` is worked back from
the due date over weekends and US federal bank holidays.

**400 cases worth handling:**

| Cause | Message |
|---|---|
| A payment is already in flight for one of these bills | `"A payment is already in flight for 1 of these bills."` |
| An occurrence is already paid | `"Already paid: …"` |
| No bank connected | `"No funding account is available. Connect a bank account first."` |

### Step 2 — Confirm

```
POST /api/v1/payments/batches/<batch_id>/confirm/
POST /api/v1/payments/<payment_id>/confirm/     ← only when batch_id was null
```

```json
{ "authorization_text": "…the exact string from step 1…" }
```

**200:**

```json
{ "success": true, "message": "Payments authorized.",
  "data": { "batch_id": "38ed6ea5-…", "payments": [ … ],
    "replayed": false } }
```

Payments move to `PROCESSING` and execution begins.

**`replayed: true`** means it was already confirmed — the request is a safe
no-op, not an error, and **no second consent is recorded**. Retrying a
confirm after a dropped connection is fine.

Also send an `Idempotency-Key` header if you can; a repeat with the same key
replays the first response byte for byte.

### Step 3 — Poll

```
GET /api/v1/payments/batches/<batch_id>/status/
```

```json
{ "success": true, "message": "Batch status fetched successfully.",
  "data": { "batch_id": "38ed6ea5-…", "status": "SUCCESSFUL",
    "total": "6400.00", "count": 2, "succeeded": 2, "failed": 0,
    "in_flight": 0, "payments": [ … ] } }
```

Stop polling when `in_flight` reaches `0`.

The batch `status` is the **worst** of its payments: one failure makes the
batch `FAILED` even if five succeeded. Read `succeeded` / `failed` for the
breakdown rather than inferring from the single value.

Per payment, for the processing drawer:

```
GET /api/v1/payments/<payment_id>/status/
```

```json
{ "data": {
    "payment_id": "8601555b-…", "reference": "SWP-20260728-0002",
    "status": "SUCCESSFUL",
    "stages": [
      { "stage": "AUTHORIZED", "status": "DONE", "order": 1, "detail": "",
        "started_at": "…", "finished_at": "…" },
      { "stage": "DEBITING",   "status": "DONE", "order": 2, … },
      { "stage": "ROUTING",    "status": "DONE", "order": 3, … },
      { "stage": "COMPLETED",  "status": "DONE", "order": 4, … }
    ],
    "progress": { "completed": 4, "total": 4, "is_complete": true } } }
```

Render `stages` **in `order`** — it is the checklist. Stage `status` is
`PENDING`, `RUNNING`, `DONE` or `FAILED`.

A failed payment gains a fifth `FAILED` stage while completed stages keep their
`DONE`, so the drawer still shows how far it got.

### Step 4 — Receipt

```
GET /api/v1/payments/<payment_id>/
```

State-aware. When settled:

```json
{ "data": { …payment fields…,
    "stages": [ … ],
    "receipt": { "recipient": "WeWork", "amount": "3200.00",
      "funding_account": "Chase Business Checking ****4821",
      "estimated_arrival": "2026-10-01",
      "reference": "SWP-20260728-0002", "paid_on": "…" },
    "failure": null,
    "progress": { "completed": 4, "total": 4, "is_complete": true } } }
```

`receipt` is `null` unless `SUCCESSFUL`; `failure` is `null` unless `FAILED`
or `RETURNED`. Exactly one is populated at a time.

---

## 3. Cancelling

```
POST /api/v1/payments/<payment_id>/cancel/
POST /api/v1/payments/batches/<batch_id>/cancel/
```

**200** with the cancelled payment (`status: "CANCELLED"`). The bill becomes
payable again.

Allowed from `SCHEDULED`, `PENDING` or `PROCESSING`, **until
`cancellation_deadline`**. After that:

```json
{ "success": false,
  "message": "The cancellation window for SWP-20260728-0005 has closed." }
```

That is **409**, not 400 — the request was well-formed, the window had closed.
Show the deadline in the UI (§1.4) so this is rare.

A payment already submitted to the processor is voided there too.

---

## 4. When a payment fails

### 4.1 Failure detail

```
GET /api/v1/payments/<payment_id>/failure/
```

```json
{ "success": true, "message": "Failure detail fetched successfully.",
  "data": {
    "payment_id": "48d98d1e-…",
    "transaction_reference": "SWP-20260728-0003",
    "amount": "3200.01", "vendor_name": "WeWork",
    "failed_at": "…", "failure_reason": "NSF",
    "failure_detail": { "attempted_amount": "3200.01",
      "available_balance": "2180.00",
      "processor_message": "Insufficient funds" },
    "due_date": "2026-11-01", "days_overdue": 0,
    "late_fee": null,
    "available_actions": ["retry", "change_method", "reschedule"] } }
```

`failure_detail` is **whatever the processor said** — its keys vary by reason.
For NSF it carries the balance at the attempt, which is the number the user
needs. Do not assume a fixed shape.

`late_fee` is `null` unless the vendor has late-fee terms recorded. When
present:

```json
"late_fee": { "amount": "160.00", "grace_days": 15,
  "days_remaining": 4, "applies": false }
```

`days_remaining` is the countdown to show; `applies` says whether the fee has
already been triggered.

### 4.2 Resolve

```
POST /api/v1/payments/<payment_id>/resolve/
```

| Action | Extra field |
|---|---|
| `retry` | — |
| `change_method` | `payment_method_id` (required) |
| `reschedule` | `scheduled_for` (required) |

**201:**

```json
{ "success": true, "message": "Payment retry scheduled.",
  "data": { "action": "retry",
    "payment": { "id": "3e8b1067-…",
      "transaction_reference": "SWP-20260728-0004",
      "status": "PENDING", … },
    "replaced_payment_id": "48d98d1e-…" } }
```

**The new payment still needs confirming** — it comes back `PENDING`, so run it
through step 2 again.

Only one payment per bill may be in flight, so resolving twice without
finishing the first returns 400.

---

## 5. Autopay

Bills with `autopay_mode: "AUTO"` pay themselves at the rail's lead time,
backed by the standing authorization captured when autopay was switched on
(see the [Bills API](bills-api-documentation.md) §3).

**There is no confirm step** — the user consented to the series, not to each
payment. Nothing for the client to call.

If the standing authorization has been revoked, autopay **does nothing** and
sends a notification titled "Autopay needs your attention". Surface it; the
bill will otherwise silently go unpaid.

`REMIND` bills generate a notification carrying deep-link ids:

```json
"metadata": { "bill_id": "…", "occurrence_id": "…" }
```

Tapping it should open the approval screen and call `POST /payments/` with that
`occurrence_id` — the ordinary create endpoint, nothing special.

---

## 6. Webhooks

Processors call `/webhooks/<processor>/` — **versionless**, because a
processor-registered URL must never move with an API version.

`/webhooks/moov/` · `/webhooks/stripe/` · `/webhooks/lob/` ·
`/webhooks/plaid/` · `/webhooks/mock/`

```json
{ "received": true, "result": "applied" }
```

Nothing for the frontend to call. It matters because **payment status can
change without the user doing anything**:

> **Late return.** ACH can claw money back days after a payment settled. A
> `SUCCESSFUL` payment becomes `RETURNED`, the bill goes back to unpaid, and
> the user gets a "Payment returned" notification.

So a receipt is **not permanent**. Refetch payment status when a screen is
reopened rather than trusting a cached "paid".

---

## 7. Vocabulary

| Enum | Values |
|---|---|
| payment `status` | `SCHEDULED` · `PENDING` · `PROCESSING` · `SUCCESSFUL` · `FAILED` · `CANCELLED` · `REFUNDED` · `RETURNED` |
| stage `stage` | `AUTHORIZED` · `DEBITING` · `ROUTING` · `COMPLETED` · `FAILED` |
| stage `status` | `PENDING` · `RUNNING` · `DONE` · `FAILED` |
| `rail` | `ACH_STANDARD` · `ACH_SAMEDAY` · `NETWORK` · `CHECK` |
| resolve `action` | `retry` · `change_method` · `reschedule` |

**There is no card rail, by design.** Bank transfer only; Swayp never renders
a card form or touches card numbers.

`transaction_reference` is `SWP-YYYYMMDD-NNNN` — a per-day sequence, readable
over the phone to support.

Money is a decimal string, USD. Dates are `YYYY-MM-DD`, timestamps ISO-8601.

---

## 8. Errors

| Status | Meaning |
|---|---|
| 400 | validation — read `errors`; also "already in flight" and "already paid" |
| 401 | missing or expired token |
| 403 | staff-only endpoint (§9) |
| 409 | cancellation window closed, or `Idempotency-Key` reused with a different body |

---

## 9. Deprecated — do not use

```
PATCH /payments/<id>/processing/
PATCH /payments/<id>/successful/
PATCH /payments/<id>/failed/
```

**Staff-only, and marked deprecated in the schema.** Status is driven by the
processor and its webhooks. A client that can declare its own payment
successful is a hole, not a feature. They return **403** for a normal user and
will be removed.

**Removed entirely:** `/api/v1/wallet/…` and `/api/v1/payment-tracking/…` both
return 404. The wallet was a stored balance, which the non-custodial model
forbids (§1.3); payment tracking is replaced by the richer `stages` array.

---

## 10. Testing against the mock

With the mock processor (the default in dev), the outcome is chosen by the
**cents** of the amount — no patching required:

| Amount ends in | Outcome |
|---|---|
| `.01` | NSF failure, with `available_balance: "2180.00"` |
| `.02` | ambiguous — submitted, then the call raises. Exercises crash recovery. |
| anything else | instant success |

So a bill of `3200.01` reliably drives the whole failure and resolution UI.

Execution is synchronous against the mock, so a payment is usually
`SUCCESSFUL` by the time confirm returns. Against real rails it will sit in
`PROCESSING` — **build the polling path, do not rely on the instant result.**

---

## 11. Quick reference

| Method | Path | Returns |
|---|---|---|
| `POST` | `/payments/` | 201 · payments + `authorization_text` |
| `POST` | `/payments/batches/<id>/confirm/` | 200 · authorized |
| `POST` | `/payments/<id>/confirm/` | 200 · single payment only |
| `GET` | `/payments/batches/<id>/status/` | 200 · aggregate, poll this |
| `GET` | `/payments/<id>/status/` | 200 · stage checklist |
| `GET` | `/payments/<id>/` | 200 · detail + receipt/failure |
| `POST` | `/payments/batches/<id>/cancel/` | 200 · or 409 |
| `POST` | `/payments/<id>/cancel/` | 200 · or 409 |
| `GET` | `/payments/<id>/failure/` | 200 · reason, balance, late fee |
| `POST` | `/payments/<id>/resolve/` | 201 · a new payment to confirm |
| `GET` | `/payments/history/` | paginated history |
| `POST` | `/webhooks/<processor>/` | processor only |
