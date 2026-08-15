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

> **Build the list screen on `GET /bills/occurrences/`, not `GET /bills/`.**

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
GET /api/v1/bills/occurrences?status=&vendor=&date_from=&date_to=&page=1
```

```json
{
  "success": true,
  "message": "Bill occurrences fetched successfully.",
  "data": [
    { "id": "219b2fdf-…", "bill_id": "d788620d-…",
      "vendor_id": "0ec2bf6c-…", "vendor_name": "WeWork", "vendor_logo": "",
      "category_name": "Rent", "due_date": "2026-09-01",
      "amount": "3200.00", "status": "UPCOMING", "autopay_mode": "REMIND" }
  ],
  "pagination": { "page": 1, "pageSize": 20, "totalPages": 1,
                  "totalItems": 1, "hasNext": false, "hasPrevious": false }
}
```

Note `data` **and** `pagination` both at the top level.

Each row carries `vendor_name`, `vendor_logo` and `category_name` already —
no second request to render the list.

### Summary chips

```
GET /api/v1/bills/summary
```

```json
{ "total_due_this_month": "0.00", "upcoming_count": 1, "due_count": 0,
  "overdue_count": 0, "total_bills": 1, "paid_count": 0 }
```

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

Excludes anything already `SCHEDULED` or `PAID`, so it is the "what still
needs paying" list rather than a date filter.

---

## 4. The bill wizard

```
POST /api/v1/bills/create
```

```json
{ "vendor": "<vendor_id>", "category": "<category_id>",
  "bill_type": "FIXED", "amount": "500.00",
  "frequency": "MONTHLY", "anchor_date": "2026-10-01",
  "autopay_mode": "REMIND", "notes": "",
  "payment_method": "<method_id>" }
```

`frequency`: `WEEKLY` · `BIWEEKLY` · `MONTHLY` · `QUARTERLY` · `YEARLY`
`bill_type`: `FIXED` or `VARIABLE`

**201** returns a review summary for the wizard's closing screen.

### Step 4 has a trap ⚠️

The payment-method step is served by
[`GET vendors/<id>/payment-methods/`](e3-vendors.md) — **not** by anything
under `bills/`, and it needs no `bill_id`, because the bill does not exist
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
{ "id": "d788620d-…", "vendor_name": "WeWork", "vendor_logo": "",
  "bill_type": "FIXED", "amount": "3200.00", "category_name": "Rent",
  "frequency": "MONTHLY", "anchor_date": "2026-09-01",
  "autopay_mode": "REMIND", "payment_method": "ACH", "notes": "",
  "next_due": "2026-09-01", "…": "…" }
```

⚠️ **`overdue_amount`, `days_overdue` and `total_paid` are numbers here**, not
decimal strings, unlike everywhere else. Coerce.

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
[vendors/qr/decode/](e3-vendors.md). One code path, two entry points.

---

## 8. Order to build

1. **`GET /bills/occurrences/`** — the main list. Everything else hangs off it.
2. **Summary chips + next-due** — same screen, two cheap calls.
3. **Detail** with the payments and invoice tabs.
4. **The wizard** — vendor → category → amount → method → autopay.

Run a bank scan first ([E5](e5-banking.md)) and the list has four real bills
with schedules before you write the wizard.
