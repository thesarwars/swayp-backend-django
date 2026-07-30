# E8 — Dashboard, Reports & Notifications

The home screen in one call, the payments report, 1099, and the notification
centre.

← [Index](README.md) · Prev: [E7](e7-ai-advisor.md) · Next: [E9 Billing](e9-billing.md)

---

## 1. Home — one call, whole screen

```
GET /api/v1/dashboard/home/?tab=upcoming
```

```json
{
  "greeting": { "name": "Ada" },
  "stats": { "due_this_month": "0.00", "total_bills": 1, "paid": 0 },
  "recent_bills": [],
  "vendors_preview": [
    { "id": "0ec2bf6c-…", "name": "WeWork", "logo": "", "category": "Rent",
      "monthly_amount": "0.00", "rail": "ACH" }
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
and its numbers reconcile with [`bills/summary/`](e4-bills.md) and
[`vendors/summary/`](e3-vendors.md) by construction.

### The pay panel picks its own tab

`active_tab` falls back **overdue → due → upcoming**: if nothing is overdue it
shows due, and if nothing is due it shows upcoming. So the panel is never
empty while the user has anything outstanding.

**Honour `active_tab` from the response** on first paint rather than defaulting
to a tab yourself. `?tab=overdue|due|upcoming` overrides it once the user
clicks.

`pay_panel.items` rows are the same shape as
[`bills/occurrences/`](e4-bills.md) — one row component, two screens.

### Profile summary

```
GET /api/v1/dashboard/profile-summary/
```

Read-only, for the account chip in the header. To **edit** anything, use
[`users/profile/`](e2-authentication.md).

---

## 2. Payments report

```
GET /api/v1/reports/?vendor=&date_from=&date_to=&status=&page=1
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

### Export is refused on purpose ⚠️

```
GET /api/v1/reports/?export=csv     → 405
```

```json
{ "success": false,
  "message": "Report export is not supported yet. Read the JSON table from GET /api/v1/reports/ instead." }
```

The format is undecided (CSV vs PDF), so the hook refuses rather than guessing.
**Hide the export button** until it ships.

---

## 3. 1099 — plan-gated

```
GET /api/v1/reports/1099/?year=2026
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
[`billing/subscription/`](e9-billing.md) so the user doesn't discover it by
clicking.

**`unattributed` matters.** It is spend that could not be tied to a vendor
with tax details. Show it as a separate warning row — a 1099 that silently
omits money is worse than one that flags it.

---

## 4. Notifications

```
GET   /api/v1/notifications/?page=1
PATCH /api/v1/notifications/<id>/read/
PATCH /api/v1/notifications/read-all/
```

```json
{ "success": true, "message": "Success", "data": [],
  "pagination": { "page": 1, "pageSize": 20, "totalPages": 1,
                  "totalItems": 0, "hasNext": false, "hasPrevious": false } }
```

Each notification carries `type`, `title`, `message`, `read_at` and a
`metadata` object with deep-link ids (`bill_id`, `occurrence_id`,
`payment_id`, `fee_charge_id`). **Route from `metadata`, not by parsing the
message.**

Notifications are **personal, not account-wide** — a team member sees their
own, not the owner's. This is the one place that scopes to the user rather
than the account.

### Preferences

```
GET   /api/v1/notifications/preferences/
PATCH /api/v1/notifications/preferences/
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

1. **`dashboard/home/`** — one call, most of the app's first screen.
2. **Notifications list + read** — the bell.
3. **Preferences matrix.**
4. **Reports table** with filters and totals.
5. **1099**, gated on plan.
