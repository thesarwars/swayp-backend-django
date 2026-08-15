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
  "source": "MANUAL", "directory_verified": false,
  "late_fee_amount": null, "late_fee_grace_days": null,
  "payment_methods": [
    { "id": "d4507e72-…", "method_type": "ACH", "is_primary": true,
      "supports_same_day": false, "provider": "MOOV",
      "account_ref": "****8837", "account_holder_name": "WeWork Inc",
      "aba_bank_name": "Chase Bank", "payee_verified": false,
      "check_legal_name": "", "street": "", "city": "", "state": "",
      "zip_code": "", "check_memo": "", "schedule": null }
  ],
  "total_paid": "0.00",
  "monthly_spend": [ { "month": "2025-08", "total": "0.00" } ],
  "next_bill": null,
  "bills": []
} 
```

`monthly_spend` is a fixed 12-month series — render it as a chart without
filling gaps yourself.

> `total_paid` comes back as a **number** in some responses and a string in
> others. Coerce it.

`payee_verified` is set by provider-run verification, which isn't wired. **It
will always be `false`** — don't build a trust badge that never lights up.

---

## 4. Payment methods

```
GET  /api/v1/vendors/<vendor_id>/payment-methods
POST /api/v1/vendors/<vendor_id>/payment-methods
POST /api/v1/vendors/<vendor_id>/payment-methods/<method_id>/set-primary
DELETE .../payment-methods/<method_id>/
```

Three method types, and the fields differ per type:

| `method_type` | Needs |
|---|---|
| `NETWORK` | `provider`, `provider_token` |
| `ACH` | `provider`, `provider_token`, `account_last4`, `account_holder_name` |
| `CHECK` | `check_legal_name`, `street`, `city`, `state`, `zip_code` |

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

### Validating a routing number first

```
POST /api/v1/banking/routing/validate    { "routing_number": "021000021" }
```

⚠️ **A bad routing number is a 200, not a 400.** The *request* succeeded; the
*number* didn't. Branch on `data.valid`, and show `data.bank_name` when it is
true. Rate limited to 30/min.

---

## 5. Directory search — the biller typeahead

```
GET /api/v1/vendors/directory-search?q=chase
```

Paginated `{ items, pagination }`. Results are seeded mock data, not a live
directory, but the shape is final.

Use it to help someone add a known biller. It supersedes the old
`providers/search/`, which has been removed.

---

## 6. QR capture

```
POST /api/v1/vendors/qr/decode    { "payload": "name=Acme&routing=…" }
```

Bare object. **422** when the payload is unreadable — that is "scan again",
not a server error.

The parser reads `k=v` pairs and returns a `provenance` field; expect
`guessed` for unfamiliar codes and **let the user confirm before saving**. The
format is provisional.

---

## 7. Deleting

`DELETE /api/v1/vendors/<id>` is a **soft delete** — 204, and the vendor
disappears from the default list but is still readable under
`?status=DELETED`. Bills and payment history that reference it survive.

Deleting the **primary** payment method promotes another automatically, so the
rail chip on the vendor row keeps working. Deleting the last one leaves the
vendor with none and `payment_rail: null`.

---

## 8. Order to build

1. **List + summary** — the vendors screen.
2. **Detail** — spend panel and methods.
3. **Add vendor** — directory search or manual, then a payment method.
4. **QR** — an accelerator on the add form, not a separate flow.

Vendors mostly arrive by themselves: one bank scan ([E5](e5-banking.md))
detects four and imports them with methods attached. Build the read screens
first and you'll have data to look at.
