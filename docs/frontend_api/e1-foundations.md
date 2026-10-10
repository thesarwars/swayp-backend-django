# E1 — Foundations

E1 ships almost no endpoints of its own. It ships the **rules every other
epic obeys**, and every one of them shows up in a response you will render.

Read this once; the other nine guides assume it.

← [Index](README.md) · Next: [E2 Authentication](e2-authentication.md)

---

## 1. Dates are business days, and the calendar is Eastern

Payment scheduling runs on a US business-day calendar with federal bank
holidays. That is why an ACH payment created on a Friday is initiated the
following Wednesday rather than three calendar days later.

You never compute these. The API returns `initiated_date`, `estimated_arrival`
and `cancellation_deadline` already worked out — **render them, don't derive
them.**

### The one that will bite you ⚠️

```json
"cancellation_deadline": "2026-08-29T03:59:00Z"
```

That is **11:59 PM Eastern on August 28**, serialized as UTC. The promise is a
wall clock — "cancel before 11:59 PM today" — and it holds across daylight
saving because the server stores it as an aware Eastern datetime.

**Render it in `America/New_York`, not the device timezone.** A user in
California shown their local time will be told the wrong hour.

The same cutoff decides whether same-day ACH is still offered today (see
[E9](e9-billing.md) §fees).

---

## 2. Idempotency

Every endpoint a retry could duplicate accepts an `Idempotency-Key` header.
**This is the complete list; no other endpoint reads the header:**

| Endpoint | Without a key, a retry would… |
|---|---|
| `POST /payments` | create a second payment |
| `POST /payments/<id>/confirm`, `POST /payments/batches/<id>/confirm` | confirm twice |
| `POST /payments/<id>/resolve` | create a second replacement payment |
| `POST /banking/link/exchange` | link the bank twice (or hit a false 402 on Founding) |
| `POST /banking/scans/<id>/import` | create the bills twice |
| `POST /bills/create` | create a second bill, and with autopay a second authorization |
| `POST /vendors`, `POST /vendors/<id>/payment-methods` | save a duplicate payee |
| `POST /billing/subscription` | start a second subscription |


```
POST /api/v1/payments
Idempotency-Key: 8f14e45f-ceea-467a-9f1c-1b8a4a2f0a11
```

- Same key, same body → the **original response** is replayed. Safe to retry.
- Same key, **different** body → **409** `code: "idempotency_key_reused"`.
- Same key while the first is still running → **409**
  `code: "idempotency_in_progress"`; wait and retry.
- A request that **failed** (any 4xx/5xx) releases its key, so retrying with
  it runs the request again.
- Omitted → the request is processed normally.
- Keys are per user and per endpoint.

Generate one UUID per user intent, not per network attempt. Retrying a
timed-out request must reuse the same key, or you will create two payments.

---

## 3. Reference data you fetch once

```
GET /api/v1/bill-categories
```

```json
{ "success": true, "message": "Bill categories fetched successfully.",
  "data": [ { "id": "…", "name": "Rent", "icon": "…", "color": "#3B82F6",
              "displayOrder": 1 } ] }
```

The key is **`display_order`** (also sent as the older `displayOrder`, see
[One casing](../frontend-integration-guide.md#one-casing)). The list is
already sorted by it.
Cache it — it changes rarely and every bill and vendor form needs it.

**`displayOrder` is unique**, so it is a stable way to pick and order
categories, for example Home's first four badges. Two categories never share
a number, and renaming one never reorders the list. Match a category to its
artwork by `id` (or `displayOrder`), not by name. Only active categories are
listed, and there is no separate `code`.

---

## 4. Providers — the biller directory cache

```
GET /api/v1/providers?search=chase&categoryId=…&page=1&pageSize=20
```

The global catalogue of known billers. **Not the user's vendors** — those are
[E3](e3-vendors.md). Use this to help someone pick a known biller; use
`vendors` for what they have actually saved.

> `providers/search` was removed — it duplicated `providers?search=`. For
> the biller typeahead use
> [`vendors/directory-search`](e3-vendors.md) instead.

---

## 5. Everything is scoped to the account

Every list endpoint filters to the caller's account already. You never send a
user id, and you cannot ask for someone else's data — a resource owned by
another account returns **404, not 403**, so the API does not confirm the id
exists.

---

## 6. Providers are mocked, so nothing external is required

The whole product runs with no third-party accounts:

| Domain | Mock behaviour |
|---|---|
| Bank data | `public-mock-chase`, `public-mock-bofa`, `public-mock-wellsfargo`, `public-mock-usbank` — each yields the same 12-month history and 4 detected bills |
| Money movement | payments execute end to end against a mock processor |
| Checks | printed and mailed by a mock |
| Email/OTP | logged, not sent, in dev |
| Directory | seeded data, not a live biller directory |
| Billing | `mock` records entitlements and charges nothing; `stripe` collects for real |

**Response shapes are final** — swapping in a real provider is a config change
on the server, not an API change. Build against these.

---

## 7. Audit trail

Consent-bearing actions (payment authorization, autopay, AI consent) record IP
and user agent server-side from the request. You do not send them, and you
should not try to — a client-supplied IP is not evidence of anything.
