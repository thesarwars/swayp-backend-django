# E3 — Vendors

Payees, their payment methods, the biller directory and QR capture.

← [Index](README.md) · Prev: [E2](e2-authentication.md) · Next: [E4 Bills](e4-bills.md)

⚠️ **This is the family that does *not* use the standard envelope.** List
endpoints return `{ items, pagination }` and detail/create/update return a
**bare object with no wrapper at all**. See [E1](e1-foundations.md).

---

## 1. Vendor list

```
GET /api/v1/vendors?search=&category=&rail=&status=&page=1&pageSize=20
```

```json
{
  "items": [
    { "id": "0ec2bf6c-…", "name": "WeWork", "logo": "",
      "status": "ACTIVE", "category": "653f035b-…", "category_name": "Rent",
      "created_at": "2026-08-01T10:00:00Z", "updated_at": "2026-09-12T08:30:00Z",
      "business_type": "", "directory_verified": false,
      "payment_rail": "ACH", "recurring_amount": "3200.00",
      "amount_period": "MONTHLY", "next_due": "2026-09-01" }
  ],
  "pagination": { "page": 1, "pageSize": 20, "totalPages": 1,
                  "totalItems": 1, "hasNext": false, "hasPrevious": false }
}
```

`payment_rail` is the **primary** method's type. `recurring_amount`,
`amount_period` and `next_due` describe the vendor's nearest unsettled
occurrence, and are all `null` for a vendor with no upcoming bill.

`rail=` filters on the primary method (`NETWORK` / `ACH` / `CHECK`), and
`status=` accepts `ACTIVE` or `DELETED` — deletion is soft, so a deleted
vendor is still readable under that filter.

Each row has `status`, `category` (id) and `category_name`, so the card's
pill and category line need no second call, plus `created_at` and
`updated_at`. There is no "Assigned Bill Payer": that field was dropped from
the design.

**Category is optional on `POST /vendors`.** Leave it out and the vendor is
filed under the default category ("Other"). The user can change it later
with `PATCH`. An inactive category is refused.

## 2. Summary chips

```
GET /api/v1/vendors/summary
```

```json
{ "total": 1, "network": 0, "ach": 1, "check": 0, "check_total": "0.00" }
```

Bare object — no `data`, no `success`.

---

## 3. Vendor detail

```
GET /api/v1/vendors/<vendor_id>
```

Returns the vendor, **all** its payment methods, and the spend panel:

```json
{
  "id": "0ec2bf6c-…", "name": "WeWork", "category": "653f035b-…",
  "contact_name": "Dana Lee", "contact_phone": "+14155550101",
  "contact_email": "ap@wework.example",
  "source": "MANUAL", "directory_verified": false,
  "late_fee_amount": null, "late_fee_grace_days": null,
  "payment_methods": [
    { "id": "d4507e72-…", "method_type": "ACH", "is_primary": true,
      "supports_same_day": false, "provider": "STRIPE",
      "account_ref": "****8837", "account_type": "CHECKING",
      "account_holder_name": "WeWork Inc", "network_payee_ref": "",
      "aba_bank_name": "Chase Bank", "payee_verified": false,
      "check_legal_name": "", "street": "", "city": "", "state": "",
      "zip_code": "", "check_memo": "", "schedule": null }
  ],
  "total_paid": "0.00",
  "monthly_spend": [ { "month": "2025-08", "total": "0.00" } ],
  "next_bill": { "occurrence_id": "…", "bill_id": "…",
                 "due_date": "2026-11-01", "amount": "3200.00" },
  "bills": [
    { "occurrence_id": "…", "bill_id": "…", "category": "Rent",
      "amount": "3200.00", "due_date": "2026-11-01", "status": "UPCOMING" } ]
}
```

`bills` is the vendor's recent bill occurrences, each with a status chip
computed now (`UPCOMING`, `DUE`, `OVERDUE`, `SCHEDULED`, `PAID`). `next_bill`
is the nearest unsettled one, or `null`.

`monthly_spend` is a fixed 12-month series — render it as a chart without
filling gaps yourself.

All money here (`total_paid`, `monthly_spend[].total`, `next_bill.amount`,
`bills[].amount`) is a **2-decimal string**, `"0.00"` when zero.

`PATCH /api/v1/vendors/<id>` takes `name`, `category`, `notes`,
`contact_name`, `contact_phone` and `contact_email`, and answers with **this
full vendor**, so there is no need to refetch. The contact fields are also
accepted on `POST /vendors`. They are for the user's own records: Swayp
never contacts them. Each is `""` when unset. A malformed email is a 400.

`payee_verified` is set by provider-run verification, which isn't wired. **It
will always be `false`** — don't build a trust badge that never lights up.

---

## 4. Payment methods

```
GET  /api/v1/vendors/<vendor_id>/payment-methods
POST /api/v1/vendors/<vendor_id>/payment-methods
PATCH /api/v1/vendors/<vendor_id>/payment-methods/<method_id>
POST /api/v1/vendors/<vendor_id>/payment-methods/<method_id>/set-primary
DELETE /api/v1/vendors/<vendor_id>/payment-methods/<method_id>
```

**What the writes return.**
- `POST /vendors` answers **201 with the full vendor**: the same shape as
  `GET /vendors/<id>`, including `id` and `payment_methods[].account_ref`.
- Adding a method (`POST`) and editing one (`PATCH`) answer with the method's
  **read shape**: `id`, `is_primary`, `account_ref` (`****4821`). The
  `provider_token` is **never** sent back.
- **A vendor's first method becomes primary automatically**, including for
  vendors imported from a bank scan with no method. There is no need to call
  `set-primary` after adding it. A later method becomes primary only if you
  send `is_primary: true`.

Three method types, and the fields differ per type:

| `method_type` | Needs |
|---|---|
| `NETWORK` | `network_payee_ref` (a directory hit's `external_id`, §5) |
| `ACH` | `provider`, `provider_token`, `account_last4`, `account_holder_name` |
| `CHECK` | `check_legal_name`, `street`, `city`, `state`, `zip_code` |

**`provider` is `STRIPE` or `MOCK`**, and the token must be one that provider
could have issued: a Stripe bank token starts `btok_`, `ba_`, `pm_` or `src_`.
Anything else is a 400 on `provider_token`. `MOCK` takes any token, but only
on a server running the mock processor, as dev does; it's a 400 on `provider`
where real money moves.

**Getting a token today:** no tokenizing processor is live yet. ACH moves to
Stripe Treasury, which is waiting on Stripe's private-preview access (see
`docs/stripe-treasury-integration-plan.md`). Until then, send
`"provider": "MOCK"` with any token on dev. Swayp will **never** accept raw
routing or account numbers, even encrypted (BRD §3.4), so don't build a form
that posts them here.

### Raw bank numbers are refused ⚠️

This is the most important rule in E3. Sending a routing and account number
gets a **400**:

```json
{ "errors": { "provider": ["This field is required."],
              "provider_token": ["This field is required."],
              "account_last4": ["This field is required."] } }
```

**Swayp never stores raw bank details** (BRD §3.4). The number goes to the
processor, which returns a token; you send the token plus the last four
digits. The API enforces this at the boundary, so raw numbers cannot get in
even by mistake.

`account_ref` in responses is the masked form (`"****8837"`) — that is all
that is ever stored, and all you can ever display.

**Getting a token: not available yet.** ACH runs on Stripe (Stripe Treasury,
PRD D-1), and the flow that turns a vendor's routing and account number into
a Stripe token is part of the Treasury integration. That is **on hold** until
Stripe grants access (see `docs/stripe-treasury-integration-plan.md`). It
will be server-side: the app will send the numbers to a Swayp endpoint once,
Swayp passes them to Stripe, and only the token and last 4 are stored. Until
then, ship check-by-mail and directory (NETWORK) vendors in release builds.

**Dev and staging:** send `provider: "STRIPE"` and any token that isn't
masked, for example `pm_mock_<uuid>`. It's stored as given, and payments run
on the mock processor, which never uses it. Any `provider` text is accepted
today, but send `STRIPE`. `MOOV` is gone.

### Validating a routing number first

```
POST /api/v1/banking/routing/validate    { "routing_number": "021000021" }
```

⚠️ **A bad routing number is a 200, not a 400.** The *request* succeeded; the
*number* didn't. Branch on `data.valid`, and show `data.bank_name` when it is
true. Show `data.message` as the reason:

| Input | Status | Body |
|---|---|---|
| A real routing number | 200 | `valid: true`, `bank_name`, `aba_verified: true` |
| Wrong length or letters (`12345`, `abc`) | 200 | `valid: false`, `"Routing number must be 9 digits."` |
| Bad prefix | 200 | `valid: false`, `"Routing number does not begin with a valid ABA prefix."` |
| Bad checksum | 200 | `valid: false`, `"Routing number failed the ABA checksum."` |
| Masked (`****0021`) | **400** | `errors.routing_number: ["Send the routing number, not a masked value."]` |
| Empty | **400** | `errors.routing_number: ["This field may not be blank."]` |
| Over 30 per minute | **429** | `{ success: false, message: "Request was throttled. Expected available in N seconds." }` plus a **`Retry-After`** header (seconds) |

---

## 5. Directory search — the biller typeahead

```
GET /api/v1/vendors/directory-search?q=chase
```

Paginated `{ items, pagination }`. Results are seeded mock data, not a live
directory, but the shape is final:

```json
{ "items": [
    { "external_id": "dir-verizon", "name": "Verizon Business",
      "category": "Telecom", "category_id": "7a1d…",
      "verified": true, "speed": "Same day", "network": "NETWORK" } ],
  "pagination": { "page": 1, "pageSize": 20, "totalPages": 1,
                  "totalItems": 1, "hasNext": false, "hasPrevious": false } }
```

An empty `q` returns nothing. `category` is the directory's name for it, and
`category_id` is the matching Swayp category, or `null` when there's no match.

**Adding a hit as a vendor:**

```json
POST /api/v1/vendors
{ "name": "<hit.name>",
  "category": "<hit.category_id>",
  "source": "DIRECTORY",
  "payment_method": { "method_type": "NETWORK",
                      "network_payee_ref": "<hit.external_id>" } }
```

Leave `category` out when `category_id` is `null`; the vendor is then filed
under "Other". The vendor remembers the directory biller it came from.
`verified` and `speed` are for the result row's badges.

Use it to help someone add a known biller. It supersedes the old
`providers/search`, which has been removed.

---

## 6. QR capture

```
POST /api/v1/vendors/qr/decode    { "payload": "name=Acme&routing=…" }
```

Bare object. **422** when the payload is unreadable — that is "scan again",
not a server error. The 422 body is the standard envelope,
`{ "success": false, "message": "…" }`, the same as `bills/qr/decode`. It used
to be `{ "detail": "…" }`.

The parser reads `k=v` pairs and returns a `provenance` field; expect
`guessed` for unfamiliar codes and **let the user confirm before saving**. The
format is provisional.

---

## 7. Deleting

`DELETE /api/v1/vendors/<id>` is a **soft delete** — 204, and the vendor
disappears from the default list but is still readable under
`?status=DELETED`.

**Its bills stop with it.** Each of the vendor's bills is deleted the same
way a bill delete does it:
- upcoming unpaid occurrences are removed, so no reminders and no new due
  dates;
- the autopay authorization is revoked, so **autopay never pays a deleted
  vendor**;
- **paid history is kept**, so payments and receipts still show.

**Refused while money is moving:** a vendor with a payment scheduled or in
flight is a 400 on `errors.vendor`. Cancel the payment or wait for it to
settle first.

**Undo:**

```
POST /api/v1/vendors/<id>/restore
```

Answers with the vendor detail. The bills deleted *with* the vendor come
back, with their upcoming occurrences regenerated, **on REMIND**: their
autopay authorization was revoked, so turning autopay back on needs the user's
consent again. A bill deleted separately before the vendor stays deleted.
Restoring a vendor that isn't deleted is a 400.

Deleting the **primary** payment method promotes another automatically, so the
rail chip on the vendor row keeps working. Deleting the last one leaves the
vendor with none and `payment_rail: null`.

---

## 7b. Recent activity

```
GET /api/v1/vendors/activity?page=1&pageSize=20
```

```json
{ "items": [
    { "id": "…", "action": "METHOD_ADDED", "label": "Payment method added",
      "vendor_id": "0ec2bf6c-…", "vendor_name": "WeWork",
      "actor_name": "Ada Reed", "created_at": "2026-10-10T09:12:00Z" } ],
  "pagination": { "page": 1, "pageSize": 20, "…": "…" } }
```

Newest first, for the whole account. `action` is one of `CREATED`,
`UPDATED`, `DELETED`, `RESTORED`, `METHOD_ADDED`, `METHOD_UPDATED`,
`METHOD_REMOVED` or `PRIMARY_CHANGED`. Show `label` as it is.
- `vendor_name` is the name **at the time**, so the feed reads correctly
  after a rename or delete.
- `vendor_id` is `null` if the vendor no longer exists.
- `actor_name` is who did it (the owner or a team member), or `null` for
  vendors created by a bank-scan import.

Recording started on 2026-10-10. Earlier changes are not in the feed.

## 8. Order to build

1. **List + summary** — the vendors screen.
2. **Detail** — spend panel and methods.
3. **Add vendor** — directory search or manual, then a payment method.
4. **QR** — an accelerator on the add form, not a separate flow.

Vendors mostly arrive by themselves: one bank scan ([E5](e5-banking.md))
detects four and imports them with methods attached. Build the read screens
first and you'll have data to look at.
