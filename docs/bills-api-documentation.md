# Bills API Documentation

Everything the bill-management screens need: the create wizard, the bills list,
occurrence status, autopay consent, and the vendor endpoints the wizard depends
on.

**Base URL:** `/api/v1/`
**Auth:** every endpoint requires `Authorization: Bearer <access_token>`.

All responses in this document were captured from the running API, not written
from the spec.

---

## 1. Read this first

### 1.1 A Bill is a rule. A BillOccurrence is a due date.

This is the single most important idea in the API.

A **Bill** is a recurring rule — "WeWork, $3,200, monthly, starting Aug 1". It
has **no status**. It is never "paid".

A **BillOccurrence** is one cycle of that rule — "WeWork, $3,200, due Sep 1".
This is what the user actually pays, and it is what carries a status.

So on the bills screen:

- **"Total Bills: 6"** counts **bills**.
- **"Overdue 14 / Due 9 / Upcoming 14"** counts **occurrences**.

Those numbers come from different endpoints and will not add up to each other.
That is correct, not a bug.

### 1.2 Status is computed, never stored

`UPCOMING`, `DUE` and `OVERDUE` are derived from the due date **every time you
read**. There is no background job that flips them.

| Condition | Status you get |
|---|---|
| `due_date` is in the future | `UPCOMING` |
| `due_date` is today | `DUE` |
| `due_date` has passed | `OVERDUE` |
| A payment is in flight | `SCHEDULED` |
| Paid | `PAID` |

`SCHEDULED` and `PAID` always win over the date. A bill due today reads `DUE`
the moment the date rolls over — you never need to refresh to "catch up".

### 1.3 There are two response shapes ⚠️

The API is **not** consistent about this yet. Handle both.

**Shape A — envelope.** Used by everything under `/bills/` and
`/bill-categories/`:

```json
{ "success": true, "message": "...", "data": { } }
```

**Shape B — bare paginated.** Used by `/vendors/` and
`/vendors/<id>/payment-methods/`:

```json
{ "items": [ ], "pagination": { "page": 1, "pageSize": 20,
  "totalPages": 1, "totalItems": 1, "hasNext": false, "hasPrevious": false } }
```

`POST /vendors/qr/decode/` returns a **bare object** with neither wrapper.

Write one small helper that unwraps `data` / `items` and use it everywhere.

---

## 2. The create wizard, step by step

This is the order to call things in. Nothing here needs a `bill_id`, so the
whole wizard runs before anything is saved.

### Step 1 — Pick a vendor

```
GET /api/v1/vendors/?search=wew&pageSize=20
```

```json
{
  "items": [
    {
      "id": "a191c086-2b5f-460e-be87-45e81631d8a9",
      "name": "WeWork",
      "logo": "https://cdn.swayp.com/logos/wework.png",
      "business_type": "Coworking",
      "directory_verified": true,
      "payment_rail": "ACH"
    }
  ],
  "pagination": { "page": 1, "pageSize": 20, "totalPages": 1,
    "totalItems": 1, "hasNext": false, "hasPrevious": false }
}
```

Filters: `search` (name contains), `category` (id), `rail`
(`NETWORK|ACH|CHECK`), `status` (defaults to `ACTIVE`).
Paging: `page`, `pageSize` (max 100).

`directory_verified` drives the "Verified" badge. `payment_rail` is the
vendor's **primary** method, for the rail chip.

### Step 2 — Pick a category

```
GET /api/v1/bill-categories/
```

```json
{ "success": true, "message": "Success",
  "data": [ { "id": "096afe26-...", "name": "Commercial Rent",
    "icon": "https://cdn.swayp.com/icons/rent.png",
    "color": "#4F46E5", "displayOrder": 1 } ] }
```

Note `displayOrder` is camelCase here. It is the only camelCase field in the
bills flow.

### Step 3 — Amount, frequency, first due date

No API call. Collect `bill_type`, `amount`, `frequency`, `anchor_date`.

`anchor_date` is the **first** due date. Everything else is derived from it, so
send the real first date — not "today".

Month-ends are handled for you. Anchor on Jan 31 and you get Feb 28, **Mar 31**,
Apr 30 — the 31st comes back once the month is long enough.

### Step 4 — Pick a payment method (and see when it must start)

```
GET /api/v1/vendors/<vendor_id>/payment-methods/?due_date=2026-11-30&amount=3200.00
```

Pass the `anchor_date` from step 3 as `due_date`. Each method comes back with a
`schedule` block:

```json
{
  "items": [
    {
      "id": "2923ad26-...",
      "method_type": "ACH",
      "is_primary": true,
      "account_ref": "****8837",
      "aba_bank_name": "Chase Bank",
      "payee_verified": false,
      "schedule": {
        "rail": "ACH_STANDARD",
        "due_date": "2026-11-30",
        "lead_business_days": 2,
        "initiate_by": "2026-11-25",
        "estimated_arrival": "2026-11-30",
        "can_meet_due_date": true
      }
    },
    {
      "id": "64ce1784-...",
      "method_type": "CHECK",
      "check_legal_name": "WeWork Inc",
      "street": "115 W 18th St", "city": "New York",
      "state": "NY", "zip_code": "10011",
      "schedule": {
        "rail": "CHECK", "due_date": "2026-11-30",
        "lead_business_days": 5, "initiate_by": "2026-11-20",
        "estimated_arrival": "2026-11-30", "can_meet_due_date": true
      }
    }
  ],
  "pagination": { }
}
```

| Field | Meaning |
|---|---|
| `initiate_by` | Swayp must start the payment on this date |
| `lead_business_days` | Business days of head start the rail needs |
| `estimated_arrival` | When the vendor gets the money |
| `can_meet_due_date` | `false` → **grey this method out**, it can no longer land in time |

Weekends and US federal bank holidays are already accounted for. In the example
above the ACH lead steps over Thanksgiving.

**Omit `due_date` and `schedule` is `null`** on every row — so only send it on
the wizard's method step.

Never render `account_last4` yourself; use the pre-masked `account_ref`
(`"****8837"`). Raw bank numbers are never returned by any endpoint.

### Step 5 — Autopay choice, then create

If the user picks **Remind me**, send `autopay_mode: "REMIND"` and **no**
`autopay_consent`.

If the user picks **Auto-pay**, you must show authorization text, get an
explicit acceptance, and send both back verbatim. See §3.

---

## 3. Autopay consent (read this before building the toggle)

Autopay is a recurring bank debit, so it is legally gated. The rules:

1. `autopay_mode: "AUTO"` **requires** an `autopay_consent` block. Without it
   the request is rejected and **no bill is created at all**.
2. `authorization_text` must be **the exact wording you displayed**, not a
   template id. It is stored so it can be reproduced later.
3. `autopay_mode: "REMIND"` must **not** include `autopay_consent`. Sending one
   is a 400 — this is deliberate, so a consent block is never silently dropped.
4. Turning autopay off revokes the authorization. Turning it back on requires a
   **fresh** consent block; the old one is not reused.
5. Deleting a bill revokes its authorization.

```json
"autopay_consent": {
  "accepted": true,
  "authorization_text": "I authorize Swayp to debit my account $3,200.00 monthly for WeWork until I revoke this authorization."
}
```

The server also records the client IP and User-Agent. If it cannot determine a
client IP the request is rejected rather than filing an inaccurate record — if
you see that error, check your proxy is forwarding `X-Forwarded-For`.

---

## 4. Endpoint reference

### 4.1 Create a bill

```
POST /api/v1/bills/create/
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `vendor` | uuid | yes | must belong to the user |
| `category` | uuid | yes | |
| `amount` | decimal string | yes | > 0 |
| `frequency` | enum | yes | `MONTHLY` `QUARTERLY` `WEEKLY` `ONE_TIME` |
| `anchor_date` | `YYYY-MM-DD` | yes | first due date |
| `bill_type` | enum | no | `FIXED` (default) or `VARIABLE` |
| `autopay_mode` | enum | no | `REMIND` (default) or `AUTO` |
| `payment_method` | uuid | no | must belong to the vendor |
| `source` | enum | no | `MANUAL` (default) `QR` `DETECTED` |
| `notes` | string | no | |
| `autopay_consent` | object | only when `AUTO` | see §3 |

**201** — the response is the wizard's review screen:

```json
{
  "success": true,
  "message": "Bill created successfully.",
  "data": {
    "id": "04d1beee-1ac7-4687-9a64-cb819739b4d4",
    "vendor": "WeWork",
    "category": "Commercial Rent",
    "amount": "3200.00",
    "frequency": "MONTHLY",
    "bill_type": "FIXED",
    "autopay_mode": "AUTO",
    "autopay_authorized": true,
    "payment_method": "ACH",
    "next_due_date": "2026-08-01",
    "summary": "Swayp will pay WeWork $3,200.00 on August 1, 2026."
  }
}
```

`summary` is built server-side and is safe to render directly. For `REMIND` it
reads *"We'll remind you to pay WeWork $3,200.00 on August 1, 2026."*

Occurrences are created immediately — the bill has due dates the moment this
returns.

**400 — AUTO without consent:**

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "autopay_consent": [
    "Autopay requires an accepted authorization with the text shown to the user." ] } }
```

### 4.2 List bills

```
GET /api/v1/bills/
```

```json
{ "success": true, "message": "Bills retrieved successfully.",
  "data": [ { "id": "04d1beee-...", "vendor": "WeWork",
    "category": "Commercial Rent", "amount": "3200.00",
    "frequency": "MONTHLY", "anchor_date": "2026-08-01",
    "autopay_mode": "AUTO", "bill_type": "FIXED",
    "payment_method": "ACH" } ] }
```

> ⚠️ **This returns bills (rules), not occurrences, and is not paginated or
> filtered yet.** For the due-date rows your list screen actually shows, use
> §4.3. See §7.

### 4.3 Occurrences — the rows for the list screen ⭐

```
GET /api/v1/bills/occurrences/?status=&vendor=&date_from=&date_to=&page=&pageSize=
```

**This is the endpoint the bills list screen is built on.** Each row is one due
date.

```json
{
  "success": true,
  "message": "Bill occurrences fetched successfully.",
  "data": [
    { "id": "7491b811-...", "bill_id": "2dd75375-...",
      "vendor_id": "38250c28-...", "vendor_name": "WeWork",
      "vendor_logo": "https://cdn.swayp.com/logos/wework.png",
      "category_name": "Commercial Rent", "due_date": "2026-07-15",
      "amount": "3200.00", "status": "OVERDUE", "autopay_mode": "REMIND" },
    { "id": "0d71c184-...", "bill_id": "2dd75375-...",
      "vendor_id": "38250c28-...", "vendor_name": "WeWork",
      "vendor_logo": "https://cdn.swayp.com/logos/wework.png",
      "category_name": "Commercial Rent", "due_date": "2026-08-15",
      "amount": "3200.00", "status": "UPCOMING", "autopay_mode": "REMIND" }
  ],
  "pagination": { "page": 1, "pageSize": 20, "totalPages": 1,
    "totalItems": 2, "hasNext": false, "hasPrevious": false }
}
```

| Query param | Effect |
|---|---|
| `status` | `UPCOMING` · `DUE` · `OVERDUE` · `SCHEDULED` · `PAID` — filters on the **computed** status, so it matches the chip |
| `vendor` | vendor id |
| `date_from` / `date_to` | `YYYY-MM-DD`, inclusive |
| `page` / `pageSize` | default 20, max 100 |

`id` is the **occurrence** id — that is what you pass to the pay endpoint.
`bill_id` is what you pass to detail, invoice and payment history.

Soft-deleted bills drop out automatically.

### 4.3b Upcoming occurrences (narrow convenience view)

```
GET /api/v1/bills/occurrences/upcoming/
```

Unsettled occurrences due today or later, unpaginated, with fewer fields.
Fine for a small "what's next" widget; use §4.3 for the list screen.

### 4.4 Summary — the tab counts

```
GET /api/v1/bills/summary/
```

```json
{ "success": true, "message": "Bills summary fetched successfully.",
  "data": { "total_due_this_month": "0.00", "upcoming_count": 3,
    "due_count": 0, "overdue_count": 0,
    "total_bills": 6, "paid_count": 0 } }
```

`total_due_this_month`, `upcoming_count`, `due_count` and `overdue_count` count
**occurrences** and exclude anything already paid or scheduled.
`total_due_this_month` is what is still owed this calendar month.

The remaining two are not the same unit and do not follow that rule:

- `total_bills` counts **bills** — live ones, i.e. `deleted_at IS NULL`, not
  occurrences. It equals the row count of the unpaginated §4.1 list. "Overdue 14
  / Due 9 / Upcoming 14" and "Total Bills 6" only reconcile because they count
  different things.
- `paid_count` counts occurrences whose stored status is `PAID` and whose
  `due_date` falls in the current calendar month — the same month window
  `total_due_this_month` uses, so the two read as one card.

A `SCHEDULED` occurrence (payment in flight) is in **neither**
`total_due_this_month` nor `paid_count`, and in none of the three counts.

"This month" and "today" are the *Eastern* calendar month and day, not UTC — the
same day every other bills read uses, so an evening request does not get
tomorrow's answer. `GET /banking/onboarding-summary/` and
`GET /dashboard/home/` re-publish these numbers and cannot disagree with them.

### 4.5 Next due

```
GET /api/v1/bills/next-due/
```

```json
{ "success": true, "message": "Next due bill fetched successfully.",
  "data": { "id": "52684969-...", "vendor_name": "WeWork",
    "vendor_logo": "https://cdn.swayp.com/logos/wework.png",
    "amount": "3200.00", "due_date": "2026-08-01",
    "category": "Commercial Rent" } }
```

Powers *"Next up: Verizon $389 due Dec 15"*. Skips anything paid or scheduled.

**Empty state — `data` is `null`, still a 200:**

```json
{ "success": true, "message": "No upcoming bills found.", "data": null }
```

### 4.6 Bill detail

```
GET /api/v1/bills/<bill_id>/details/
```

```json
{ "success": true, "message": "Bill details fetched successfully.",
  "data": { "id": "04d1beee-...", "vendor_name": "WeWork",
    "vendor_logo": "https://cdn.swayp.com/logos/wework.png",
    "bill_type": "FIXED", "amount": "3200.00",
    "category_name": "Commercial Rent", "frequency": "MONTHLY",
    "anchor_date": "2026-08-01", "autopay_mode": "AUTO",
    "payment_method": "ACH", "notes": "HQ floor 3",
    "next_due": "2026-08-01", "overdue_amount": 0,
    "days_overdue": 0, "total_paid": 0 } }
```

`days_overdue` renders *"11 days overdue"*; it is counted from the **oldest**
unpaid past-due occurrence. Both it and `overdue_amount` are `0` when nothing
is late.

> ⚠️ `overdue_amount` and `total_paid` come back as **numbers** (`0`), while
> `amount` is a **string** (`"3200.00"`). Coerce both.

### 4.7 Update a bill

```
PATCH /api/v1/bills/<bill_id>/update/
```

Every wizard field is editable. Send only what changed. The response is the
same review object as §4.1, refreshed.

**Two side effects to be aware of:**

- Changing `frequency` or `anchor_date` **rebuilds the schedule**. Unpaid future
  occurrences are deleted and regenerated, so **occurrence ids change**. Refetch
  §4.3 afterwards. Paid and scheduled occurrences are untouched.
- Changing `amount` updates unpaid future occurrences on `FIXED` bills. On
  `VARIABLE` bills per-occurrence amounts are left alone.

To change autopay, send `autopay_mode` — plus `autopay_consent` when switching
to `AUTO` (§3).

### 4.8 Delete a bill

```
DELETE /api/v1/bills/<bill_id>/details/
```

```json
{ "success": true, "message": "Bill deleted successfully." }
```

A **soft** delete. Unpaid future occurrences are removed and any autopay
authorization is revoked, but **paid history is preserved** — so vendor spend
totals and reports stay correct. The bill disappears from all listings.

### 4.9 Mark an occurrence paid

```
PATCH /api/v1/bills/occurrences/<occurrence_id>/pay/
```

```json
{ "payment_reference": "MOOV-TX-4417" }
```

```json
{ "success": true, "message": "Bill marked as paid successfully.", "data": null }
```

Takes an **occurrence** id, not a bill id. The occurrence leaves the summary
counts immediately (in the captured run `upcoming_count` went 3 → 2). Paying an
already-paid occurrence returns an error.

> **Superseded.** Real payment execution now exists — see the
> [Payments API](payments-api-documentation.md). Use `POST /payments/` with
> this occurrence id instead; it moves money and keeps the occurrence in
> step. This endpoint remains only for reconciling a payment made outside
> Swayp.

### 4.10 Payment history

```
GET /api/v1/bills/<bill_id>/payments/
```

```json
{
  "success": true,
  "message": "Payment history fetched successfully.",
  "data": [
    { "id": "dc3f5110-...", "occurrence_id": "7491b811-...",
      "due_date": "2026-07-15", "amount": "3200.00", "fee": "0.00",
      "total": "3200.00", "currency": "USD",
      "payment_status": "SUCCESSFUL", "payment_method": "CHECK",
      "transaction_reference": "TX-OK-1",
      "created_at": "2026-07-28T11:21:40.238237Z" },
    { "id": "664ca3f8-...", "occurrence_id": "7491b811-...",
      "due_date": "2026-07-15", "amount": "3200.00", "fee": "0.00",
      "total": "3200.00", "currency": "USD",
      "payment_status": "FAILED", "payment_method": "CHECK",
      "transaction_reference": "TX-FAIL-1",
      "created_at": "2026-07-28T11:21:40.214237Z" }
  ],
  "pagination": { "page": 1, "pageSize": 20, "totalPages": 1,
    "totalItems": 2, "hasNext": false, "hasPrevious": false }
}
```

Newest first, paginated. Note both rows above share one `occurrence_id`: a
**retry is a separate payment against the same due date**, so group by
`occurrence_id` if you want to collapse attempts.

`payment_status` is the payment's own lifecycle (`SCHEDULED`, `PENDING`,
`PROCESSING`, `SUCCESSFUL`, `FAILED`, `CANCELLED`, `REFUNDED`, `RETURNED`) —
not the occurrence status from §1.2.

### 4.11 Invoice

```
GET /api/v1/bills/<bill_id>/invoice/
```

```json
{
  "success": true,
  "message": "Invoice fetched successfully.",
  "data": {
    "bill_id": "2dd75375-...", "occurrence_id": "7491b811-...",
    "vendor_name": "WeWork",
    "vendor_logo": "https://cdn.swayp.com/logos/wework.png",
    "category": "Commercial Rent", "bill_type": "FIXED",
    "frequency": "MONTHLY", "amount": "3200.00",
    "due_date": "2026-07-15", "status": "OVERDUE",
    "autopay_mode": "REMIND", "payment_method": "CHECK", "notes": "",
    "payment_reference": "SWAYP-2DD75375-20260715",
    "qr_payload": "SWAYP:vendor=WeWork;ref=SWAYP-2DD75375-20260715;amount=3200.00;due=2026-07-15"
  }
}
```

Defaults to the bill's next open occurrence. `qr_payload` is the string to
render as the invoice QR — it round-trips through §4.12, so scanning a Swayp
invoice prefills the wizard.

Rendered from bill data only; there is no OCR in v1.

### 4.12 Bill QR decode

```
POST /api/v1/bills/qr/decode/
```

Accepts JSON `{"payload": "..."}` or a multipart `image` upload. Fields are
coerced for the wizard — `amount` to a decimal, `due_date` to a date:

```json
{
  "success": true,
  "message": "QR decoded successfully.",
  "data": {
    "vendor_name": "WeWork", "category": null, "amount": "3200.00",
    "due_date": "2026-09-01", "payment_ref": "WW-88",
    "provenance": { "vendor_name": "detected", "amount": "detected",
      "due_date": "detected", "payment_ref": "detected" }
  }
}
```

`provenance` drives the per-field chips: `detected` means it was genuinely read
out of the payload, `guessed` means it was inferred — show those as needing
confirmation. **A value that fails to coerce loses its provenance entry
entirely** rather than being reported as successfully read, so a field present
in `data` but absent from `provenance` should be treated as unknown.

**422 on anything unreadable:**

```json
{ "success": false,
  "message": "QR payload is not readable — no recognisable content." }
```

Treat 422 as "scan again", not as a server error.

> There is also `POST /api/v1/vendors/qr/decode/` for the add-vendor flow. It
> shares the same parser but returns a **bare object** (no envelope) and adds
> `directory_match`. Use the bills one in the bill wizard.

---

## 5. Vocabulary

| Enum | Values |
|---|---|
| `frequency` | `MONTHLY` `QUARTERLY` `WEEKLY` `ONE_TIME` |
| `bill_type` | `FIXED` `VARIABLE` |
| `autopay_mode` | `AUTO` `REMIND` |
| occurrence `status` | `UPCOMING` `DUE` `OVERDUE` `SCHEDULED` `PAID` |
| `source` | `MANUAL` `QR` `DETECTED` |
| `method_type` | `NETWORK` `ACH` `CHECK` |
| `rail` | `NETWORK` `ACH_STANDARD` `ACH_SAMEDAY` `CHECK` |

Money is always a **decimal string** (`"3200.00"`), USD, except where §4.6
notes otherwise. Dates are `YYYY-MM-DD`. Ids are UUIDs.

---

## 6. Errors

Validation failures under `/bills/`:

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "<field>": ["<message>"] } }
```

| Status | Meaning |
|---|---|
| 400 | validation — read `errors` per field |
| 401 | missing or expired token |
| 404 | not found, or not owned by this user |
| 422 | QR payload unreadable |

A bill belonging to another user returns **404**, not 403.

---

## 7. Known gaps — do not design around these yet

| Gap | Impact |
|---|---|
| `GET /bills/` returns bill **rules**, unpaginated and unfiltered | Not a bug, but not the list screen. Use §4.3. This endpoint is for "how many bills do I have", not "what's due". |
| Payment figures are zero until payments run | The payment-history endpoint (§4.10) and the vendor spend series are wired and tested, but nothing has actually paid anything yet, so they return empty/zero in practice. |
| QR payload format is provisional | PRD §10-Q6 is open. The parser reads `k=v` pairs and rejects unreadable input; expect `guessed` provenance for unfamiliar codes. |
| Two response envelopes (§1.3) | Unwrap defensively. |

---

## 8. Quick reference

| Method | Path | Returns |
|---|---|---|
| `GET` | `/bill-categories/` | envelope · category list |
| `GET` | `/vendors/` | paginated · vendor list |
| `GET` | `/vendors/<id>/payment-methods/?due_date=&amount=` | paginated · methods + `schedule` |
| `POST` | `/banking/routing/validate/` | envelope · ABA check (see note) |
| `POST` | `/bills/create/` | envelope · review summary |
| `GET` | `/bills/` | envelope · bill rules |
| `GET` | `/bills/occurrences/` | envelope + pagination · **the list screen** |
| `GET` | `/bills/summary/` | envelope · tab counts |
| `GET` | `/bills/next-due/` | envelope · one occurrence or `null` |
| `GET` | `/bills/occurrences/upcoming/` | envelope · narrow convenience view |
| `POST` | `/bills/qr/decode/` | envelope · prefill fields · 422 if unreadable |
| `GET` | `/bills/<id>/details/` | envelope · bill detail |
| `PATCH` | `/bills/<id>/update/` | envelope · review summary |
| `DELETE` | `/bills/<id>/details/` | envelope · confirmation |
| `GET` | `/bills/<id>/payments/` | envelope + pagination · payment history |
| `GET` | `/bills/<id>/invoice/` | envelope · invoice + `qr_payload` |
| `PATCH` | `/bills/occurrences/<id>/pay/` | envelope · `data: null` |

### ABA routing validation

Used by the vendor ACH form, not the bill wizard, but worth knowing:

```
POST /api/v1/banking/routing/validate/   { "routing_number": "021000021" }
```

```json
{ "success": true, "message": "Valid – JPMorgan Chase Bank (ABA verified)",
  "data": { "valid": true, "bank_name": "JPMorgan Chase Bank",
    "aba_verified": true, "bank_known": true,
    "message": "Valid – JPMorgan Chase Bank (ABA verified)" } }
```

> ⚠️ **An invalid routing number is still HTTP 200** with `success: true` and
> `data.valid: false`. The request succeeded; the number didn't. **Branch on
> `data.valid`, not the status code.**
>
> `valid` and `bank_known` are separate: a number can pass the checksum while
> being absent from the bank directory. That is still valid — just show it
> without a bank name.
