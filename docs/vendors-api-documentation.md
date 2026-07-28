# Vendors API Documentation

Vendors are the user's payees. Each one holds one or more payment methods —
`NETWORK`, `ACH`, or `CHECK` — and is what a bill is paid to.

**Base URL:** `/api/v1/vendors/`
**Auth:** every endpoint requires `Authorization: Bearer <access_token>`.

Every response body below was captured from the running API.

Related: [Bills API](bills-api-documentation.md) — the bill wizard consumes
§2 and §5 of this document.

---

## 1. Read this first

### 1.1 Three response shapes ⚠️

The vendor endpoints are **not** consistent about envelopes. Handle all three.

| Shape | Where |
|---|---|
| `{ "items": [...], "pagination": {...} }` | list endpoints — §2, §5.1, §7 |
| a **bare object**, no wrapper | detail, create, update, set-primary — §3, §4, §5 |
| `{ "success": false, "message": "...", "errors": {...} }` | all errors |

Success responses have **no** `success` field; failures do. Branch on the HTTP
status, not on the body.

### 1.2 Raw bank numbers are never stored or returned

Routing and account numbers never reach this API. The client tokenizes with the
money-movement provider first and sends back only `provider_token`,
`account_last4` and `aba_bank_name`.

Read-side responses expose `account_ref` — already masked as `"****8837"`.
Render that. There is no endpoint that returns a full account number, by design.

### 1.3 `category` is a UUID here, not a name

Vendor responses return `"category": "d8ef16db-…"`. (The bills API returns
category *names*.) Resolve it against
`GET /api/v1/bill-categories/`.

---

## 2. List vendors

```
GET /api/v1/vendors/
```

```json
{
  "items": [
    { "id": "ba977f47-...", "name": "Con Edison", "logo": "",
      "business_type": "", "directory_verified": false,
      "payment_rail": "NETWORK" },
    { "id": "dc9fdffc-...", "name": "WeWork", "logo": "",
      "business_type": "", "directory_verified": false,
      "payment_rail": "ACH" }
  ],
  "pagination": { "page": 1, "pageSize": 20, "totalPages": 1,
    "totalItems": 3, "hasNext": false, "hasPrevious": false }
}
```

| Query param | Effect |
|---|---|
| `search` | name contains, case-insensitive |
| `category` | category UUID |
| `rail` | `NETWORK` · `ACH` · `CHECK` — matches the vendor's **primary** method |
| `status` | `ACTIVE` (default) · `INACTIVE` · `DELETED` |
| `page` | 1-based |
| `pageSize` | default 20, max 100 |

`payment_rail` is the primary method's type and drives the rail chip. It is
`null` when the vendor has no primary method — see §8.

Sorted by name.

---

## 3. Create a vendor

```
POST /api/v1/vendors/
```

One endpoint, three branches. `payment_method.method_type` picks the branch and
determines which fields are required.

| Field | Type | Required |
|---|---|---|
| `name` | string | yes |
| `category` | uuid | yes |
| `source` | enum | yes — `DIRECTORY` `QR` `MANUAL` `IMPORT` |
| `notes` | string | no |
| `payment_method` | object | yes — see below |

**NETWORK** — requires `network_payee_ref`:

```json
{ "name": "Con Edison", "category": "<category_id>", "source": "DIRECTORY",
  "payment_method": { "method_type": "NETWORK",
    "network_payee_ref": "payee_9f21" } }
```

**ACH** — requires `provider`, `provider_token`, `account_last4`,
`account_holder_name`. Tokenize client-side first; never send raw numbers:

```json
{ "name": "WeWork", "category": "<category_id>", "source": "MANUAL",
  "notes": "HQ floor 3",
  "payment_method": { "method_type": "ACH", "provider": "MOOV",
    "provider_token": "pm_moov_7c11", "account_last4": "8837",
    "account_type": "CHECKING", "account_holder_name": "WeWork Inc",
    "aba_bank_name": "Chase Bank" } }
```

**CHECK** — requires `check_legal_name`, `street`, `city`, `state`, `zip_code`:

```json
{ "name": "Landlord LLC", "category": "<category_id>", "source": "MANUAL",
  "payment_method": { "method_type": "CHECK",
    "check_legal_name": "Landlord LLC", "street": "115 W 18th St",
    "city": "New York", "state": "NY", "zip_code": "10011",
    "check_memo": "Unit 4" } }
```

**201** — the full vendor, bare, with the method embedded:

```json
{
  "id": "dc9fdffc-ad43-45ad-bd85-a8063cc43bdf",
  "name": "WeWork",
  "category": "d8ef16db-08b6-4093-b633-3b139f49d052",
  "logo": "", "business_type": "", "notes": "HQ floor 3",
  "source": "MANUAL", "directory_verified": false,
  "late_fee_amount": null, "late_fee_grace_days": null,
  "payment_methods": [
    { "id": "4764ebb9-...", "method_type": "ACH", "is_primary": true,
      "supports_same_day": false, "provider": "MOOV",
      "account_ref": "****8837", "account_holder_name": "WeWork Inc",
      "aba_bank_name": "Chase Bank", "payee_verified": false,
      "check_legal_name": "", "street": "", "line2": "", "city": "",
      "state": "", "zip_code": "", "check_memo": "", "schedule": null }
  ]
}
```

The first method is automatically the primary one — you do not need to send
`is_primary`.

**400 — branch validation errors nest under `payment_method`:**

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "payment_method": {
    "provider_token": ["This field is required."],
    "account_last4": ["This field is required."],
    "account_holder_name": ["This field is required."] } } }
```

Note the extra level of nesting — `errors.payment_method.<field>`, not
`errors.<field>`.

> `payee_verified` and `supports_same_day` are **server-controlled**. Sending
> them is silently ignored; they are set by the provider, not the client.

---

## 4. Vendor detail, update, delete

### 4.1 Detail

```
GET /api/v1/vendors/<vendor_id>/
```

Returns the same bare object as §3's 201, including `payment_methods`.

### 4.2 Update

```
PATCH /api/v1/vendors/<vendor_id>/
```

Only three fields are editable:

```json
{ "name": "WeWork", "category": "<category_id>", "notes": "renewed" }
```

> ⚠️ **The response is only the fields you can edit**, not the full vendor:
>
> ```json
> { "name": "WeWork", "category": "c6fae969-...", "notes": "renewed" }
> ```
>
> There is no `id`. Re-fetch §4.1 if you need the whole record back.

To change how a vendor is paid, use the payment-methods endpoints in §5 — not
this one.

### 4.3 Delete

```
DELETE /api/v1/vendors/<vendor_id>/
```

**204**, empty body. This is a **soft** delete: the vendor's status becomes
`DELETED` and it drops out of the default list, but the row survives so payment
history stays intact.

A deleted vendor still appears under `GET /vendors/?status=DELETED`, but
`GET /vendors/<id>/` returns **404**.

---

## 5. Payment methods

A vendor may hold several — e.g. ACH *and* CHECK — with exactly one primary.

### 5.1 List

```
GET /api/v1/vendors/<vendor_id>/payment-methods/
```

```json
{
  "items": [
    { "id": "0c80588a-...", "method_type": "ACH", "is_primary": true,
      "supports_same_day": false, "provider": "MOOV",
      "account_ref": "****8837", "account_holder_name": "WeWork Inc",
      "aba_bank_name": "Chase Bank", "payee_verified": false,
      "check_legal_name": "", "street": "", "line2": "", "city": "",
      "state": "", "zip_code": "", "check_memo": "", "schedule": null }
  ],
  "pagination": { "page": 1, "pageSize": 20, "totalPages": 1,
    "totalItems": 1, "hasNext": false, "hasPrevious": false }
}
```

Sorted primary-first, then by type.

#### Lead times — pass `due_date`

```
GET /api/v1/vendors/<vendor_id>/payment-methods/?due_date=2026-11-30&amount=3200.00
```

Each row's `schedule` fills in (it is `null` without `due_date`):

```json
"schedule": { "rail": "ACH_STANDARD", "due_date": "2026-11-30",
  "lead_business_days": 2, "initiate_by": "2026-11-25",
  "estimated_arrival": "2026-11-30", "can_meet_due_date": true }
```

| Field | Meaning |
|---|---|
| `initiate_by` | the payment must start on this date |
| `lead_business_days` | business days of head start the rail needs |
| `estimated_arrival` | when the vendor receives it |
| `can_meet_due_date` | `false` → **grey the method out**, it can no longer land in time |

Weekends and US federal bank holidays are already handled — in the example the
ACH lead steps over Thanksgiving. `amount` is accepted and validated but does
not yet change the result.

This is what the bill wizard's method step calls.

### 5.2 Add

```
POST /api/v1/vendors/<vendor_id>/payment-methods/
```

Same per-branch required fields as §3. **201** returns the bare method.

> ⚠️ A method added this way is **not** primary — `is_primary` comes back
> `false`. Call §5.4 if it should become the default.

### 5.3 Retrieve / update / delete one

```
GET|PUT|PATCH|DELETE /api/v1/vendors/<vendor_id>/payment-methods/<method_id>/
```

`GET` returns the bare method. `DELETE` returns **204** with an empty body.

### 5.4 Set primary

```
POST /api/v1/vendors/<vendor_id>/payment-methods/<method_id>/set-primary/
```

```json
{ "message": "Primary payment method updated." }
```

Atomic — the previous primary is demoted in the same transaction, so a vendor
never has two.

---

## 6. Directory search

```
GET /api/v1/vendors/directory-search/?q=veri
```

```json
{
  "items": [
    { "id": "67729293-...", "provider_name": "Verizon Business",
      "provider_code": "VZW-BIZ", "category": "Telecom",
      "logo": "https://cdn.swayp.com/logos/vz.png",
      "supports_auto_pay": true }
  ],
  "pagination": { "page": 1, "pageSize": 20, "totalPages": 1,
    "totalItems": 1, "hasNext": false, "hasPrevious": false }
}
```

Matches `provider_name` or `provider_code`, active entries only. Here `category`
**is** a name, unlike §1.3.

This searches the global biller directory, not the user's vendors. Use a result
to prefill §3 with `source: "DIRECTORY"`.

---

## 7. QR decode

```
POST /api/v1/vendors/qr/decode/
```

Accepts JSON `{"payload": "..."}` or a multipart `image` upload. Returns a
**bare object**:

```json
{ "vendor_name": "WeWork", "category": null, "payment_ref": "WW-88",
  "amount": "3200", "due_date": "2026-09-01",
  "provenance": { "vendor_name": "detected", "amount": "detected",
    "due_date": "detected", "payment_ref": "detected" },
  "directory_match": null }
```

`provenance` drives the per-field chips — `detected` was genuinely read from the
payload, `guessed` was inferred and should be confirmed by the user.

**422 on anything unreadable:**

```json
{ "detail": "QR payload is not readable — no recognisable content." }
```

Treat 422 as "scan again", not as a server error. The payload format is not
finalised, so expect `guessed` results for unfamiliar codes.

---

## 8. Known gaps — do not design around these yet

| Gap | Impact |
|---|---|
| **Deleting the primary method leaves no primary** | The vendor keeps its other methods but `payment_rail` becomes `null` and the rail chip disappears. Call §5.4 on a remaining method after deleting a primary. |
| `summary.check_total` is always `"0.00"` | Do not display it; it needs payment amounts that do not exist yet. |
| Vendor detail has no spend history | No 12-month series, total-paid, or next-bill. Not available. |
| `PATCH` returns only the editable fields (§4.2) | Re-fetch for the full record. |
| No ABA routing validation | `POST /banking/routing/validate/` does not exist. The "Valid – Chase Bank (ABA verified)" indicator cannot be built yet; `aba_bank_name` is whatever the client supplies. |
| Three response envelopes (§1.1) | Unwrap defensively. |

---

## 9. Vocabulary

| Enum | Values |
|---|---|
| `method_type` | `NETWORK` `ACH` `CHECK` |
| `rail` | `NETWORK` `ACH_STANDARD` `ACH_SAMEDAY` `CHECK` |
| `source` | `DIRECTORY` `QR` `MANUAL` `IMPORT` |
| `status` | `ACTIVE` `INACTIVE` `DELETED` |
| `account_type` | `CHECKING` `SAVINGS` |

Money is a decimal string, USD. Dates are `YYYY-MM-DD`. Ids are UUIDs.

---

## 10. Errors

| Status | Meaning |
|---|---|
| 400 | validation — read `errors`, remembering the nesting in §3 |
| 401 | missing or expired token |
| 404 | not found, deleted, **or owned by another user** |
| 422 | QR payload unreadable |

A vendor belonging to someone else returns **404**, not 403 — the API does not
confirm that the id exists.

---

## 11. Quick reference

| Method | Path | Returns |
|---|---|---|
| `GET` | `/vendors/` | paginated |
| `POST` | `/vendors/` | bare vendor · 201 |
| `GET` | `/vendors/<id>/` | bare vendor |
| `PATCH` | `/vendors/<id>/` | bare · editable fields only |
| `DELETE` | `/vendors/<id>/` | 204 · soft delete |
| `GET` | `/vendors/summary/` | bare counts |
| `GET` | `/vendors/<id>/payment-methods/?due_date=&amount=` | paginated · `schedule` when `due_date` given |
| `POST` | `/vendors/<id>/payment-methods/` | bare method · 201 · not primary |
| `GET\|PUT\|PATCH\|DELETE` | `/vendors/<id>/payment-methods/<mid>/` | bare · 204 on delete |
| `POST` | `/vendors/<id>/payment-methods/<mid>/set-primary/` | `{ "message": ... }` |
| `GET` | `/vendors/directory-search/?q=` | paginated |
| `POST` | `/vendors/qr/decode/` | bare object · 422 if unreadable |

### Summary endpoint

```
GET /api/v1/vendors/summary/
```

```json
{ "total": 3, "network": 1, "ach": 1, "check": 1, "check_total": "0.00" }
```

Counts respect the same filters as §2, so `?rail=ACH` makes the summary and the
list agree.
