# E8 — Dashboard, Reports & Notifications

The home screen in one call, the payments report, 1099, and the notification
centre.

← [Index](README.md) · Prev: [E7](e7-ai-advisor.md) · Next: [E9 Billing](e9-billing.md)

---

## 1. Home — one call, whole screen

```
GET /api/v1/dashboard/home?tab=upcoming
```

```json
{
  "greeting": { "name": "Ada" },
  "unread_notification_count": 3,
  "funding_account": { "id": "…", "name": "Chase Business Checking",
                       "mask": "4821",
                       "display": "Chase Business Checking ****4821" },
  "stats": { "due_this_month": "0.00", "total_bills": 1, "paid": 0 },
  "recent_bills": [],
  "vendors_preview": [
    { "id": "0ec2bf6c-…", "name": "WeWork", "logo": "", "category": "Rent",
      "monthly_amount": "0.00", "rail": "ACH",
      "next_due": "2026-11-01", "recurring_amount": "3200.00",
      "amount_period": "MONTHLY" }
  ],
  "pay_panel": {
    "active_tab": "upcoming",
    "tabs": { "overdue": 0, "due": 0, "upcoming": 1 },
    "items": [
      { "id": "219b2fdf-…", "bill_id": "d788620d-…", "vendor_id": "0ec2bf6c-…",
        "vendor_name": "WeWork", "vendor_logo": "", "category_name": "Rent",
        "due_date": "2026-09-01", "amount": "3200.00",
        "status": "UPCOMING", "autopay_mode": "REMIND" }
    ]
  }
}
```

**Do not assemble this from bills + vendors + payments.** It is one aggregate
query set, costs a fixed number of queries however much data the account has,
and its numbers reconcile with [`bills/summary`](e4-bills.md) and
[`vendors/summary`](e3-vendors.md) by construction.

### The pay panel picks its own tab

`active_tab` falls back **overdue → due → upcoming**: if nothing is overdue it
shows due, and if nothing is due it shows upcoming. So the panel is never
empty while the user has anything outstanding.

**Honour `active_tab` from the response** on first paint rather than defaulting
to a tab yourself. `?tab=overdue|due|upcoming` overrides it once the user
clicks.

`pay_panel.items` rows are the same shape as
[`bills/occurrences`](e4-bills.md) — one row component, two screens.

### Funding account

`funding_account` is the account a payment would be debited from: the
default funding source on an active bank connection, the same rule
`POST /payments` applies when no account is named. Use it for the "From" row.
It is `null` when there is none, which is exactly when creating a payment is
refused, so show "Connect a bank" there instead of letting the user reach a
400.

### Vendor cards

`vendors_preview` is **at most 3** active vendors, highest `monthly_amount`
first, then by name.

- `monthly_amount` is the total of that vendor's bills **due in the current
  calendar month** (US Eastern), paid or not. A vendor billed $3,200 on the
  1st reads `0.00` once this month's bill is behind it and the next falls in
  next month. It is "this month", not "per month".
- `next_due`, `recurring_amount` and `amount_period` describe the vendor's
  **next unsettled bill**: its due date, its amount and its cadence. All
  three are `null` when nothing is outstanding. They are the same values and
  meaning as on `GET /vendors`.

For a "Next: Nov 1, $3,200 / month" line, use the `next_*` fields. For "this
month", use `monthly_amount`.

`unread_notification_count` is the bell badge: the **signed-in person's**
unread notifications (a team member sees their own count, not the owner's).
It is the same number as `GET notifications` → `unreadCount` and
`profile-summary` → `unreadNotificationCount`.

### Profile summary

```
GET /api/v1/dashboard/profile-summary
```

Read-only, for the account chip in the header. To **edit** anything, use
[`users/profile`](e2-authentication.md).

---

## 2. Payments report

```
GET /api/v1/reports?vendor=&date_from=&date_to=&status=&page=1
```

```json
{
  "success": true,
  "message": "Report generated.",
  "data": {
    "rows": [],
    "totals": { "count": 0, "amount": "0.00", "fee": "0.00",
                "total": "0.00", "currency": null,
                "by_status": {}, "by_currency": [] },
    "filters": { "vendor": null, "date_from": null, "date_to": null }
  },
  "pagination": { "page": 1, "pageSize": 20, "totalPages": 1,
                  "totalItems": 0, "hasNext": false, "hasPrevious": false }
}
```

`totals` covers the **whole filtered set**, not the current page — so the
figure at the top of the table stays right as the user pages.

`filters` echoes back what was applied. Render the active-filter chips from
that rather than from your own state, and a stale query string can't lie to
the user.

### Export — CSV and PDF

```
GET /api/v1/reports?export=csv     → text/csv,        swayp-payments.csv
GET /api/v1/reports?export=pdf     → application/pdf, swayp-payments.pdf
```

Both come back as **file downloads** (`Content-Disposition: attachment`), not
JSON. Trigger them with a link or `window.location`, not your `fetch` wrapper
— the unwrap helper will choke on a PDF.

⚠️ **An export ignores pagination and returns the whole filtered set**, capped
at 10,000 rows. `page` and `pageSize` are ignored; every other filter is
respected, so "export what I'm looking at" works by sending the same query
string minus the paging.

If the cap is hit, the file itself carries a note saying so — a truncated
export that looks complete is worse than one that admits it.

**An unknown format is a 400, never a silent fallback:**

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "export": ["Unsupported export format. Use one of: csv, pdf."] } }
```

`?export=` with no value is refused too — it is still someone asking for one.

---

## 3. 1099 — plan-gated

```
GET /api/v1/reports/1099?year=2026
GET /api/v1/reports/1099?export=csv|pdf
```

```json
{ "year": 2026, "rows": [],
  "totals": { "count": 0, "amount": "0.00", "fee": "0.00", "total": "0.00" },
  "unattributed": { "count": 0, "amount": "0.00", "fee": "0.00",
                    "total": "0.00" } }
```

⚠️ **403 on Founding:**

```json
{ "success": false,
  "message": "1099 reporting is available on the Standard plan and above. Upgrade your plan to run this report." }
```

Note this is a **403 with an upgrade message**, not a 402 — the message names
the plan, so display it verbatim. Gate the menu item on the plan code from
[`billing/subscription`](e9-billing.md) so the user doesn't discover it by
clicking.

The exported 1099 discloses `unattributed` on the file itself and states
that it is a data view rather than an IRS form — the caveat has to travel
with the file, because the file is what gets emailed to an accountant.

**`unattributed` matters.** It is spend that could not be tied to a vendor
with tax details. Show it as a separate warning row — a 1099 that silently
omits money is worse than one that flags it.

---

## 4. Notifications

```
GET   /api/v1/notifications?page=1&pageSize=20&category=transactions&isRead=false
PATCH /api/v1/notifications/<id>/read
PATCH /api/v1/notifications/read-all
```

```json
{ "success": true, "message": "Success", "data": [],
  "pagination": { "page": 1, "pageSize": 20, "totalPages": 1,
                  "totalItems": 0, "hasNext": false, "hasPrevious": false },
  "nextCursor": null,
  "unreadCount": 3 }
```

**Scroll with the cursor, not `page`.** New notifications arrive at the top,
so page 2 shifts by one row whenever one lands, and offset paging then
repeats or skips rows. Load the first page normally, then ask for what comes
after the last row you have:

```
GET /api/v1/notifications?pageSize=20&before=<nextCursor>
```

`nextCursor` is the id of the last row when there is more, and `null` on the
last page. With `before`, `page` is ignored and `pagination` has only
`pageSize` and `hasNext` (a cursor page has no number or total). Filters work
the same in both modes. A `before` that is not one of the caller's
notifications is a 400. To pick up new arrivals at the top, refetch the first
page, or take them from the socket.

A `page` past the end returns an empty `data` with `hasNext: false`. This
applies to every list paged with `page`, not only notifications. It used to
return the last page again.

**Filters**, all optional and applied before paging, so `totalItems` counts
only matching rows:

| Param | Values |
|---|---|
| `type` | Repeatable: `?type=BILL_DUE&type=PAYMENT_FAILED`. |
| `category` | `transactions` (PAYMENT, BILL_DUE, PAYMENT_FAILED, PAYMENT_REVERSED, AUTOPAY_EXECUTED, PAYMENT_ARRIVED, LATE_FEE_WARNING) or `promotion` (PROMOTION). SYSTEM and SECURITY appear in neither. |
| `isRead` | `true` or `false`. Omitted means both. |

`type` and `category` together return the rows that match both.

**`unreadCount` ignores the filters.** It is the bell badge, every unread
notification the person has, so the badge does not change when the user
switches chips.

Each notification carries `type`, `title`, `message`, `isRead`, `readAt`,
`createdAt` and a `metadata` object with deep-link ids. **Route from
`metadata`, not by parsing the message.**

`type` is one of: `SYSTEM`, `PAYMENT`, `PROMOTION`, `SECURITY`, `BILL_DUE`,
`PAYMENT_FAILED`, `PAYMENT_REVERSED`, `AUTOPAY_EXECUTED`, `PAYMENT_ARRIVED`,
`LATE_FEE_WARNING`. The OpenAPI schema declares the enum.

Every id key in `metadata` is a **uuid string, or absent**, never `""` or
`null`:

| `type` | Id keys in `metadata` |
|---|---|
| `PAYMENT`, `PAYMENT_FAILED`, `PAYMENT_ARRIVED`, `PAYMENT_REVERSED` | `payment_id`; plus `bill_id` and `occurrence_id` when the payment is for a bill |
| `PAYMENT` (fee refunded) | `fee_charge_id`, `payment_id` |
| `AUTOPAY_EXECUTED` | `bill_id`, `occurrence_id`, `payment_id` |
| `BILL_DUE`, `LATE_FEE_WARNING` | `bill_id`, `occurrence_id` |
| `SYSTEM` (autopay could not run) | `bill_id` |
| `SECURITY`, `PROMOTION` | none |

`metadata` can also carry display values (`vendor_name`, `amount`,
`reference`, `reason`). Treat the id keys as the contract. The same ids
arrive in push `data` as camelCase (`paymentId`, …).

Notifications are **personal, not account-wide** — a team member sees their
own, not the owner's. This is the one place that scopes to the user rather
than the account.

### Marking read

`PATCH notifications/<id>/read` answers with **the updated row** (same shape
as the list) and the badge count after the change:

```json
{ "success": true, "message": "Notification marked as read.",
  "data": { "id": "…", "isRead": true, "readAt": "2026-10-10T12:00:00Z", "…": "…" },
  "unreadCount": 2 }
```

- **Idempotent.** Marking an already-read notification is a 200 that changes
  nothing; `readAt` keeps its original time.
- **404** for an id that is not the caller's, including a team member trying
  someone else's.

`PATCH notifications/read-all` answers `data.markedCount` (how many were
unread, 0 if none) and `unreadCount` (now 0). Update the list and the badge
from these; there is no need to refetch.

### Preferences

```
GET   /api/v1/notifications/preferences
PATCH /api/v1/notifications/preferences
```

```json
{
  "channels": [
    { "key": "inApp", "label": "In-app", "supported": true,  "enabled": true  },
    { "key": "email", "label": "Email",  "supported": true,  "enabled": false },
    { "key": "sms",   "label": "SMS",    "supported": false, "enabled": false },
    { "key": "push",  "label": "Push",   "supported": false, "enabled": false }
  ],
  "preferences": [
    { "type": "SYSTEM", "label": "System", "inApp": true, "email": true,
      "sms": false, "push": false, "isDefault": true },
    { "type": "PAYMENT", "label": "Payment", "…": "…" }
  ]
}
```

**Build the matrix from `channels`, not a hardcoded list.** `supported: false`
means no delivery adapter exists — render SMS and push **disabled with a
"coming soon" hint** rather than hiding them, which is what the design shows.

`isDefault: true` means the row has never been customised; use it for a
"reset to defaults" affordance.

PATCH takes `{ "preferences": [ … ] }` — the key is **required**, and sending
bare fields is a 400.

---

## 5. Order to build

1. **`dashboard/home`** — one call, most of the app's first screen.
2. **Notifications list + read** — the bell.
3. **Preferences matrix.**
4. **Reports table** with filters and totals.
5. **1099**, gated on plan.
