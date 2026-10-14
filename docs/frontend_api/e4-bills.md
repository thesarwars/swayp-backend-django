# E4 — Bills

The bill wizard, the occurrence list, the summary chips, and the invoice.

← [Index](README.md) · Prev: [E3](e3-vendors.md) · Next: [E5 Banking](e5-banking.md)

---

## 1. The one idea to get right

**A Bill is a rule. A BillOccurrence is a due date.**

A **Bill** is "WeWork, $3,200, monthly, from Sep 1". It has **no status** and
is never "paid". A **BillOccurrence** is "WeWork, $3,200, due Sep 1" — that is
what the user pays, and what carries a status.

So on the bills screen, **"Total Bills: 6"** counts bills while
**"Overdue 14 / Due 9 / Upcoming 14"** counts occurrences. Different
endpoints, numbers that don't add up to each other. That is correct.

> **Build the list screen on `GET /bills/occurrences`, not `GET /bills`.**

## 2. Status is computed at read time

`UPCOMING`, `DUE` and `OVERDUE` are derived from the due date on **every
read** — there is no nightly job. A bill due today reads `DUE` the moment the
date rolls over; you never refresh to "catch up".

`SCHEDULED` and `PAID` are stored and always win over the date.

| Status | Means |
|---|---|
| `UPCOMING` | due after today |
| `DUE` | due today |
| `OVERDUE` | due before today, still unpaid |
| `SCHEDULED` | a payment exists for it — reminders stop |
| `PAID` | settled |

---

## 3. The list screen

```
GET /api/v1/bills/occurrences?status=&vendor=&bill=&category=&search=&date_from=&date_to=&ordering=&page=1&page_size=20
```

| Parameter | Meaning |
|---|---|
| `status` | `UPCOMING`, `DUE`, `OVERDUE`, `SCHEDULED`, `PAID`; several allowed, repeated or comma-separated |
| `vendor`, `bill`, `category` | ids; `category` allows several. `bill` gives one bill's due dates, for its page |
| `search` | the vendor name or the bill's notes contain this |
| `date_from`, `date_to` | `YYYY-MM-DD`, inclusive |
| `ordering` | `due_date` (default), `-due_date`, `amount`, `-amount`, `vendor`, `-vendor` |
| `page`, `page_size` | paging; `page_size` ≤ 100 |

An unknown value or a malformed id or date returns 400 on that field.

```json
{
  "success": true,
  "message": "Bill occurrences fetched successfully.",
  "data": [
    { "id": "219b2fdf-…", "bill_id": "d788620d-…",
      "vendor_id": "0ec2bf6c-…", "vendor_name": "WeWork", "vendor_logo": "",
      "category_id": "7a1d…", "category_name": "Rent",
      "due_date": "2026-09-01", "amount": "3200.00",
      "status": "UPCOMING", "days_overdue": 0, "autopay_mode": "REMIND",
      "payment_method": "ACH", "payment_id": null,
      "payment_status": null, "can_resolve": false }
  ],
  "pagination": { "page": 1, "pageSize": 20, "totalPages": 1,
                  "totalItems": 1, "hasNext": false, "hasPrevious": false }
}
```

Note `data` **and** `pagination` both at the top level.

Each row carries `vendor_name`, `vendor_logo` and `category_name` already —
no second request to render the list.

- `category_id`: the id behind `category_name`. Match categories by id, never
  by name.
- `days_overdue`: calendar days past due on an `OVERDUE` row, `0` otherwise.
  It is the same number bill detail reports.
- `payment_method`: the bill's saved method type (`ACH`, `CHECK`,
  `NETWORK`), or `null`.
- `payment_id`: on a `SCHEDULED` or `PAID` row, the payment behind it, so
  the row can open the payment. `null` on other rows, and on a bill marked
  paid outside Swayp.

**Filters.** Rows are ordered by `due_date`, earliest first.

| Param | Values |
|---|---|
| `status` | Several allowed: `?status=OVERDUE&status=DUE` or `?status=OVERDUE,DUE`. |
| `category` | Category ids, several allowed the same way. A non-id is a 400. |
| `vendor` | One vendor id. |
| `date_from`, `date_to` | `YYYY-MM-DD`, inclusive. |

All filters combine. For the Pay tab's "unsettled" view, use
`status=OVERDUE,DUE,UPCOMING`. For a category screen, use
`category=<id>&status=…`, with no client-side filtering.

### Summary chips

```
GET /api/v1/bills/summary
```

```json
{ "total_due_this_month": "0.00", "upcoming_count": 1, "due_count": 0,
  "overdue_count": 0, "total_bills": 1, "paid_count": 0,
  "scheduled_count": 0 }
```

`paid_count` covers this month. `scheduled_count` covers every queued
payment, any month.

`total_bills` counts **bills**; the three `_count` fields count
**occurrences**. See §1.

### Next due

```
GET /api/v1/bills/next-due
```

```json
{ "id": "219b2fdf-…", "vendor_name": "WeWork", "vendor_logo": "",
  "amount": "3200.00", "due_date": "2026-09-01", "category": "Rent" }
```

`data` is `null` when nothing is outstanding — that's the empty state, not an
error.

### Upcoming only

```
GET /api/v1/bills/occurrences/upcoming
```

Occurrences **due today or later** that are **not yet `SCHEDULED` or
`PAID`**, earliest first. **Overdue rows are not included.** For "everything
still to pay", overdue included, use
`GET bills/occurrences?status=OVERDUE,DUE,UPCOMING`.

---

## 4. The bill wizard

```
POST /api/v1/bills/create
```

```json
{ "vendor": "<vendor_id>", "category": "<category_id>",
  "bill_type": "FIXED", "amount": "500.00",
  "frequency": "MONTHLY", "anchor_date": "2026-10-01",
  "autopay_mode": "REMIND", "notes": "", "payment_ref": "WW-88",
  "payment_method": "<method_id>" }
```

`payment_ref` is the vendor's own reference for the bill (account or invoice
number), up to 100 characters. Put a scanned QR's `payment_ref` here, not in
`notes`. Bill detail returns it, and PATCH can change it.

`frequency`: `MONTHLY` · `QUARTERLY` · `WEEKLY` · `ONE_TIME`. These four
only; there is no `BIWEEKLY` or `YEARLY`.
`bill_type`: `FIXED` or `VARIABLE`
`autopay_mode`: `REMIND` (default) or `AUTO`
`source`: `MANUAL` (default), `QR` or `DETECTED`

**201** returns a review summary for the wizard's closing screen.
`PATCH bills/<id>/update` answers **200** with the same shape:

```json
{ "success": true, "message": "Bill created successfully.",
  "data": { "id": "…", "vendor": "WeWork", "category": "Rent",
            "amount": "3200.00", "frequency": "MONTHLY", "bill_type": "FIXED",
            "autopay_mode": "AUTO", "autopay_authorized": true,
            "payment_method": "ACH", "next_due_date": "2026-11-01",
            "summary": "Swayp will pay WeWork $3,200.00 on November 1, 2026." } }
```

`vendor` and `category` here are **names**, for display. `payment_method` is
the method's type (`ACH`, `CHECK`, `NETWORK`) or `null`.

### What create checks

| Field | Rule | Error |
|---|---|---|
| `vendor` | One of the account's **active** vendors | 400 `errors.vendor` |
| `category` | An **active** bill category | 400 `errors.category` |
| `payment_method` | Optional, and must belong to that vendor. **Omitted means none**: there is no default. An autopay bill with no method pays by standard ACH. | 400 `errors.payment_method` |
| `amount` | At least `0.01`, two decimals, up to 16 digits before the point | 400 `errors.amount` |
| `anchor_date` | Any date. **A past date is accepted**: it creates the current period's occurrence (which can be `OVERDUE` at once) and the ones ahead, never a backlog of past ones. | — |
| `notes` | Up to 2,000 characters | 400 `errors.notes` |
| `payment_ref` | Up to 100 characters | 400 `errors.payment_ref` |
| `autopay_mode: AUTO` | Needs `autopay_consent` (step 5). **It does not need a connected bank** to create. Without one, each autopay run fails and notifies the user, so prompt for a bank first. | 400 `errors.autopay_consent` |

**Lead time is not checked at create.** A bill due tomorrow by check is
accepted. To grey out a method that cannot make the next due date, use the
`schedule` that `GET vendors/<id>/payment-methods?due_date=&amount=` returns
for each method (step 4).

The same rules apply to `PATCH bills/<id>/update` for the fields it sends.

### Step 4 has a trap ⚠️

The payment-method step is served by
[`GET vendors/<id>/payment-methods`](e3-vendors.md) — **not** by anything
under `bills`, and it needs no `bill_id`, because the bill does not exist
yet. Pass `?due_date=&amount=` if you want lead-time hints.

### Step 5 requires consent for autopay

`autopay_mode` is `REMIND` or `AUTO`.

**`AUTO` without consent is a 400:**

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "autopay_consent": ["Autopay requires an accepted authorization."] } }
```

Autopay debits a bank account on a schedule, so it needs a NACHA standing
authorization. Show the authorization text, capture acceptance, and send it
with the request. Don't default the toggle to `AUTO`.

**Get the text from the server; don't write it yourself:**

```
POST /api/v1/bills/autopay-authorization/preview
{ "vendor": "<uuid>", "amount": "3200.00", "bill_type": "FIXED",
  "frequency": "MONTHLY", "anchor_date": "2026-11-01",
  "payment_method": "<uuid, optional>" }
```

```json
{ "success": true, "message": "Authorization text generated.",
  "data": {
    "authorization_text": "I authorize Swayp to debit Chase Business Checking ****4821 for $3,200.00 every month, starting November 1, 2026, to pay WeWork. Each payment will be executed by Stripe, Inc. over the ACH network. …",
    "funding_account": "Chase Business Checking ****4821" } }
```

Show `authorization_text` as it is, and send it back **verbatim** as
`autopay_consent.authorization_text`. That exact string is stored as what the
user agreed to. Call the preview again whenever any term changes (amount,
frequency, date, type, method), including when editing an autopay bill.
It creates nothing. `funding_account` is `null` when no bank is linked; the
text then says "my connected bank account".

### Anchor dates clamp

A monthly bill anchored on the 31st lands on Feb 28, then **back to Mar 31** —
the anchor is remembered, not compounded. You don't compute this; occurrences
arrive already generated.

---

## 5. Bill detail

```
GET /api/v1/bills/<bill_id>/details
```

```json
{ "id": "d788620d-…",
  "vendor_id": "0ec2bf6c-…", "vendor_name": "WeWork", "vendor_logo": "",
  "category_id": "7a1d…", "category_name": "Rent",
  "bill_type": "FIXED", "amount": "3200.00",
  "frequency": "MONTHLY", "anchor_date": "2026-09-01",
  "autopay_mode": "REMIND",
  "payment_method": "ACH", "payment_method_id": "5c2e…", "account_ref": "****4821",
  "notes": "",
  "next_due": "2026-11-01",
  "next_occurrence": { "id": "219b2fdf-…", "due_date": "2026-11-01",
                       "amount": "3200.00", "status": "UPCOMING" },
  "last_paid_at": "2026-10-01T14:02:11Z",
  "overdue_amount": "0.00", "days_overdue": 0, "total_paid": "6400.00" }
```

- The `*_id` fields are for the edit screen; the names are for display.
  `payment_method_id` and `account_ref` are `null` when the bill has no
  method.
- `next_occurrence` is the unsettled occurrence `next_due` describes: pay
  or schedule it by its `id`, with no second lookup. `null` when nothing is
  outstanding. `status` is `DUE` (today) or `UPCOMING`.
- `last_paid_at` is the latest time an occurrence was paid, or `null`.
- `overdue_amount` and `total_paid` are **decimal strings**, `"0.00"` when
  zero, like money everywhere else. They used to be numbers. `days_overdue`
  is an integer.

"11 days overdue" is computed server-side on the business-day calendar — take
`days_overdue` as given.

```
PATCH  /api/v1/bills/<bill_id>/update
DELETE /api/v1/bills/<bill_id>/details
GET    /api/v1/bills/<bill_id>/payments     ← payment history for this bill
GET    /api/v1/bills/<bill_id>/invoice      ← the invoice modal
```

Deleting is soft: **paid history is preserved**, and changing autopay
re-captures or revokes the authorization.

### Editing an autopay bill needs fresh consent

An autopay authorization covers the terms the user agreed to. On an `AUTO`
bill, a PATCH that changes **`amount`, `frequency`, `anchor_date`,
`bill_type` or `payment_method`** must carry a new `autopay_consent` for the
new terms. Without it the PATCH is a 400 on `errors.autopay_consent` and
**nothing is saved**:

```json
{ "amount": "4100.00",
  "autopay_consent": { "accepted": true,
                       "authorization_text": "<the text shown for the new terms>" } }
```

The old authorization is revoked and the new one recorded, so the audit trail
keeps both. Sending the same value again is not a change. `notes`,
`category` and `source` never need consent. Turning autopay off (`REMIND`)
never needs it either. On a `REMIND` bill, `autopay_consent` is a 400.

---

## 6. Marking a bill paid outside Swayp

```
PATCH /api/v1/bills/occurrences/<occurrence_id>/pay
```

```json
{ "payment_reference": "MANUAL-001" }
```

`payment_reference` is **required** — recording a payment by hand has to say
what paid it. Omitting it is a 400.

This is for bills the user settled elsewhere. To pay *through* Swayp, use
[E6](e6-payments.md).

---

## 7. QR

```
POST /api/v1/bills/qr/decode    { "payload": "…" }
```

Same parser and the same **422-on-unreadable** rule as
[vendors/qr/decode](e3-vendors.md). One code path, two entry points. Both
answer a 422 as `{ "success": false, "message": "…" }`.

```json
{ "success": true, "message": "QR decoded successfully.",
  "data": { "vendor_id": "0ec2bf6c-…", "vendor_name": "WeWork",
            "category_id": "7a1d…", "category": "Rent",
            "amount": "3200.00", "due_date": "2026-11-01",
            "payment_ref": "WW-88", "provenance": { "amount": "parsed", "…": "…" } } }
```

**Use the ids for the wizard.** `vendor_id` is the account's saved vendor
whose name matches the QR's exactly (case aside), or `null`, in which case
put `vendor_name` in the vendor search box. `category_id` is the active
category the QR names, else the matched vendor's own category, else `null`.
Nothing is created by decoding. `amount` is a decimal string like everywhere
else.

---

## 8. Order to build

1. **`GET /bills/occurrences`** — the main list. Everything else hangs off it.
2. **Summary chips + next-due** — same screen, two cheap calls.
3. **Detail** with the payments and invoice tabs.
4. **The wizard** — vendor → category → amount → method → autopay.

Run a bank scan first ([E5](e5-banking.md)) and the list has four real bills
with schedules before you write the wizard.
