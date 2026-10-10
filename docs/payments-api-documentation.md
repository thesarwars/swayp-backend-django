# Payments API Documentation

Paying bills: quoting rails, creating payments, confirming them, following
them to completion, cancelling, recovering from failure, history and
receipts.

**Base URL:** `/api/v1/payments`
**Auth:** every endpoint requires `Authorization: Bearer <access_token>`.
**Envelope:** every JSON response is `{ "success", "message", "data" }`.
Errors are `{ "success": false, "message", "errors"? }`. The OpenAPI schema at
`/api/schema` declares every body below.

Related: [Billing API](billing-api-documentation.md) (fees) ·
[Bills API](bills-api-documentation.md) ·
[Frontend guide, E6](frontend_api/e6-payments.md) (the screens, in order)

---

## 1. How a payment works

1. **Quote** (optional): what each rail costs and when it lands.
2. **Create**: reserves the work. The bill occurrence becomes `SCHEDULED`.
   **No money moves.** The answer carries the authorization text to show.
3. **Confirm**: the user agrees to that text. Money moves now, or on
   `scheduled_for`.
4. **Follow**: poll status until `progress.is_complete`.

An unconfirmed payment **lapses after 30 minutes** (`confirm_by`) and its bill
is released. It can be cancelled at any time before confirm. After confirm,
cancelling is allowed until `cancellation_deadline`.

### Payment status

| `status` | Meaning |
|---|---|
| `PENDING` | Created, not yet sent (unconfirmed, or confirmed pay-now about to send) |
| `SCHEDULED` | Future-dated (`scheduled_for`), waiting for its date |
| `PROCESSING` | Sent to the processor |
| `SUCCESSFUL` | Completed |
| `FAILED` | Failed; see the failure block and §7 |
| `CANCELLED` | Cancelled by the user or lapsed unconfirmed |
| `REFUNDED`, `RETURNED` | Reversed after completing |

### Stages

`stages[]` drives the processing screen: `AUTHORIZED` → `DEBITING` →
`ROUTING` → `COMPLETED`, or a `FAILED` row. Each has `status` (`PENDING`,
`RUNNING`, `DONE`, `FAILED`), `detail`, `started_at`, `finished_at`. An
unconfirmed payment has **no stages**: they are created at confirm.

### Rails

| `rail` | Takes | Fee |
|---|---|---|
| `ACH_STANDARD` | an ACH account | free |
| `ACH_SAMEDAY` | an ACH account, before 11:59 PM Eastern | $4.99 |
| `CHECK` | a check address | free within the plan's checks, then $2.99; `expedited` $8.99 |
| `NETWORK` | a biller-network payee | free |

The money goes to the **bill's saved payment method**, so the rail has to
suit it. An account with no plan is charged no fees.

---

## 2. Quote

```
POST /quote
{ "occurrence_ids": ["…"], "scheduled_for": null }
```

**200** `data`:

```json
{ "occurrences": [
    { "occurrence_id": "…", "default_rail": "ACH_STANDARD",
      "rails": [
        { "rail": "ACH_STANDARD", "available": true, "unavailable_reason": null,
          "fee": "0.00", "initiated_date": "2026-08-28",
          "estimated_arrival": "2026-09-01", "expedited": null },
        { "rail": "CHECK", "available": false,
          "unavailable_reason": "This vendor is paid by ACH.", "fee": "0.00",
          "initiated_date": "…", "estimated_arrival": "…",
          "expedited": { "fee": "8.99", "estimated_arrival": "…" } } ] } ] }
```

Creates and charges nothing. `default_rail` is what create uses when `rail`
is omitted.

## 3. Create

```
POST /
Idempotency-Key: <uuid>
{ "occurrence_ids": ["…"], "funding_account_id": "…?", "rail": "…?",
  "scheduled_for": "YYYY-MM-DD?", "expedited": false }
```

- `rail` omitted: each bill's own, from its saved method.
- `funding_account_id` omitted: the default funding account.
- More than one occurrence creates a batch.

**201** `data`:

```json
{ "batch_id": null,
  "payments": [ <payment> ],
  "authorization_text": "I authorize Swayp to debit …",
  "total": "3200.00" }
```

`batch_id` is `null` for a single payment. **400s:** unsupported rail; a rail
the bill's method cannot take (`errors.rail`); `expedited` on a non-check rail;
an occurrence already paid or with a payment in flight; no funding account.

### The payment object

Returned by create, confirm, cancel, resolve, batch status and detail:

```json
{ "id": "…", "transaction_reference": "SWP-20260728-0001",
  "status": "PENDING", "amount": "3200.00", "fee": "0.00", "total": "3200.00",
  "currency": "USD", "rail": "ACH_STANDARD",
  "vendor_id": "…", "vendor_name": "WeWork",
  "funding_account": "Chase Business Checking ****4821", "funding_account_id": "…",
  "bill_id": "…", "bill_occurrence": "…", "payment_method_id": "…",
  "batch": null, "initiated_date": "2026-08-28", "estimated_arrival": "2026-09-01",
  "cancellation_deadline": "2026-08-29T03:59:00Z",
  "scheduled_for": null, "expedited": false, "created_at": "…" }
```

`cancellation_deadline` is UTC on the wire and 11:59 PM **Eastern** in
meaning.

## 4. Confirm

```
POST /<payment_id>/confirm
POST /batches/<batch_id>/confirm
Idempotency-Key: <uuid>
{ "authorization_text": "<exactly what was shown>" }
```

A payment in a batch is confirmed through its batch. **200** `data`: the
payment, or for a batch `{ batch_id, payments: [<payment>], replayed }`.
Confirming twice records one authorization (`replayed: true`).

## 5. Follow

```
GET /<payment_id>              ← full detail
GET /<payment_id>/status       ← light, for polling
GET /batches/<batch_id>/status
```

**Detail** is the payment object plus:

| Field | Meaning |
|---|---|
| `stages` | §1 |
| `progress` | `{ completed, total, is_complete }`; stop polling on `is_complete` |
| `receipt` | `{ recipient, amount, funding_account, estimated_arrival, reference, paid_on }` once `SUCCESSFUL`, else `null` |
| `failure` | `{ reason, detail, can_resolve }` when `FAILED`, else `null` |
| `authorized_at` | When confirmed; `null` = not yet |
| `authorization_text` | What the user agreed to; `null` before confirm |
| `confirm_by` | When an unconfirmed payment lapses; else `null` |

**Status** `data`: `{ payment_id, reference, status, stages, progress }`.

**Batch status** `data`: `{ batch_id, status, total, count, succeeded,
failed, in_flight, payments: [<payment>] }`. The batch is `FAILED` if any
payment failed, and `SUCCESSFUL` only when all have.

## 6. Change or cancel

```
PATCH /<payment_id>                 { "scheduled_for": "YYYY-MM-DD" | null }
POST  /<payment_id>/cancel
POST  /batches/<batch_id>/cancel
```

- **PATCH** moves an **unconfirmed** payment's date in place (null = pay
  now) and answers with the detail. Confirmed: 400.
- **Cancel**: an unconfirmed payment can be cancelled any time. A confirmed
  one can be cancelled until `cancellation_deadline`, then **409**. The bill
  is released. Batch cancel cancels what it can and answers
  `{ batch_id, cancelled: [<payment>] }`; 409 if nothing could be.

## 7. Failure and recovery

```
GET  /<payment_id>/failure
POST /<payment_id>/resolve    Idempotency-Key: <uuid>
     { "action": "retry" | "change_method" | "reschedule",
       "payment_method_id": "…?", "funding_account_id": "…?", "scheduled_for": "…?" }
```

**Failure** `data` (400 if the payment did not fail):

```json
{ "payment_id": "…", "transaction_reference": "…",
  "title": "Not enough money in the account", "explanation": "…",
  "amount": "3200.01", "vendor_name": "WeWork", "failed_at": "…",
  "failure_reason": "NSF", "failure_detail": { "…": "…" },
  "due_date": "2026-09-01", "days_overdue": 3,
  "late_fee": { "amount": "50.00", "grace_days": 5, "days_remaining": 2, "applies": false },
  "available_actions": ["retry", "change_method", "reschedule"] }
```

**Resolve** creates a **new, unconfirmed** payment. **201** `data`:
`{ action, payment, replaced_payment_id, authorization_text,
requires_confirmation: true }`. Confirm the new payment with that text (§4).
`change_method` needs `payment_method_id` and takes that method's rail;
`reschedule` needs `scheduled_for`.

## 8. History and receipts

```
GET /history?status=&providerId=&categoryId=&search=&fromDate=&toDate=&page=&pageSize=
GET /<payment_id>/receipt.pdf
```

History rows are **camelCase**, with `pagination` beside `data`: `id`,
`vendorId`, `vendorName`, `billId`, `occurrenceId`, `amount`, `fee`, `total`,
`currency`, `status`, `rail`, `estimatedArrival`, `scheduledFor`,
`replacedPaymentId`, `transactionReference`, `providerReference`,
`paymentMethod`, `providerId`, `providerName`, `categoryId`, `categoryName`,
`createdAt`, `updatedAt`. Use `vendorName` as the recipient; `providerName` is
the biller directory and usually `null`.

`receipt.pdf` downloads a `SUCCESSFUL` payment's receipt; 409 before that.

## 9. Idempotency

Send an `Idempotency-Key` header on **create**, **confirm** (single and
batch) and **resolve**. A retry with the same key after a lost response
returns the original answer instead of acting twice. Use one key per user
action and reuse it only to retry that action.

## 10. Testing on the mock processor

The amount's cents choose the outcome: `.01` fails with `NSF`, `.02` loses
the response (the payment stays `PROCESSING` until the reconcile job about
30 minutes later), anything else succeeds at once.
