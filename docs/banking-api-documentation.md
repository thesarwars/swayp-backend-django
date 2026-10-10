# Banking API Documentation

The onboarding journey: connect a bank read-only, scan up to 24 months of
history, review the recurring bills we found, and import them as real bills.
Plus ABA routing validation for the vendor ACH form.

**Base URL:** `/api/v1/banking`
**Auth:** every endpoint requires `Authorization: Bearer <access_token>`.

Every response body below was captured from the running API.

Related: [Bills API](bills-api-documentation.md) · [Vendors API](vendors-api-documentation.md)

---

## 1. Read this first

### 1.1 The connection is read-only

Linking a bank lets Swayp **read** transactions. It never moves money — that
is the payments provider's job, on a separate rail.

The link is also Swayp's identity check on its own customer: proving you own
the account **is** the verification. There is no separate KYC step to build.

### 1.2 Raw bank data never reaches you

Accounts expose a four-digit `mask` and a pre-formatted `display`
(`"Chase Business Checking ****4821"`). There is no endpoint that returns a
full account number.

The provider access token is encrypted at rest, excluded from the admin, and
absent from every response. Don't look for it.

### 1.3 Response envelope

All banking endpoints use `{ "success", "message", "data" }` — the same shape
as the bills API. Errors use `{ "success": false, "message", "errors" }`.

### 1.4 Detection is deterministic, not AI

A transaction cluster becomes a candidate only when **all four** hold:

1. same normalised vendor name (`"POS DEBIT WEWORK #1123"` → `wework`),
2. amounts within tolerance of the cluster median,
3. a regular interval,
4. **at least three occurrences**.

Those are the four criteria cards on the progress screen. The same history
always produces the same candidates — no model, no randomness.

---

## 2. The onboarding flow

```
POST link/token      →  hand the token to the bank widget
POST link/exchange   →  connection created, scan starts automatically
GET  scans/<id>      →  poll until status != RUNNING
GET  scans/<id>/candidates  →  show the review list
POST scans/<id>/import      →  create the bills
GET  onboarding-summary     →  the done screen
```

### Step 1 — Get a link token

```
POST /api/v1/banking/link/token     { "platform": "ios" }   ← optional: ios, android, web
```

```json
{ "success": true, "message": "Link token created.",
  "data": { "link_token": "link-mock-96d92229-…", "expiration": null,
    "provider": "MOCK", "months_history": 24 } }
```

`months_history` is the window the scan will read, so the screens before the
link can show it from data.

Short-lived. Hand `link_token` to the bank link widget; it returns a
`public_token` when the user finishes.

### Step 2 — Exchange the public token

```
POST /api/v1/banking/link/exchange
```

```json
{ "public_token": "public-…", "consent_accepted": true }
```

> ⚠️ **`consent_accepted` must be `true`.** You must show the data-access
> disclosure and get an explicit acceptance first. The server records the
> timestamp; a connection without recorded consent is not one we can rely on.

**201** — the connection, its accounts, **and a scan that has already started**:

```json
{
  "success": true, "message": "Bank connected.",
  "data": {
    "id": "8529ed8a-…", "provider": "MOCK",
    "institution_name": "Chase Bank", "institution_logo": "",
    "status": "ACTIVE", "consented_at": "2026-07-28T12:04:14.403873Z",
    "accounts": [
      { "id": "f3369679-…", "name": "Chase Business Checking",
        "mask": "4821", "display": "Chase Business Checking ****4821",
        "account_type": "CHECKING", "is_default_funding_source": true,
        "available_balance": "41200.00", "current_balance": "41200.00",
        "balance_as_of": "2026-07-28T12:04:14.443876Z" },
      { "id": "578e047d-…", "name": "Chase Bank Savings",
        "mask": "4822", "display": "Chase Bank Savings ****4822",
        "account_type": "SAVINGS", "is_default_funding_source": false,
        "available_balance": "18750.00", "current_balance": "18750.00",
        "balance_as_of": "2026-07-28T12:04:14.443876Z" }
    ],
    "created_at": "2026-07-28T12:04:14.405874Z",
    "scan": { "id": "b8302eb4-…", "status": "RUNNING",
      "months_history": 24, "transactions_scanned": 0,
      "detected_count": 0, "error_message": "", "completed_at": null,
      "progress": { "is_complete": false, "thin_history": false } }
  }
}
```

**Take `data.scan.id` and go straight to step 3** — you do not need to start a
scan yourself.

The first **checking** account automatically becomes the funding source;
savings accounts cannot fund ACH debits.

**400 without consent:**

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "consent_accepted":
    "Bank connection requires accepting the data-access disclosure." } }
```

### Step 3 — Poll the scan

```
GET /api/v1/banking/scans/<scan_id>
```

```json
{ "success": true, "message": "Scan fetched successfully.",
  "data": { "id": "46fdcd18-…", "status": "DONE", "months_history": 24,
    "transactions_scanned": 46, "detected_count": 4,
    "error_message": "", "completed_at": "2026-07-28T12:05:39.961799Z",
    "created_at": "2026-07-28T12:05:39.690801Z",
    "progress": { "is_complete": true, "thin_history": false } } }
```

| Field | Use |
|---|---|
| `status` | `RUNNING` · `DONE` · `FAILED` |
| `detected_count` | climbs during the scan — drives *"17 recurring bills detected"* |
| `transactions_scanned` | how much history was read |
| `progress.is_complete` | stop polling when `true` |
| `progress.thin_history` | see below |
| `error_message` | populated only when `status` is `FAILED` |

**`thin_history: true` changes what "0 bills" means.** With under ~180 days of
history, a scan finding nothing means *not enough history to tell*, not *you
have no recurring bills*. Say so, rather than showing an empty state that
implies the user has no bills.

Poll every second or two. `detected_count` is written as the scan works, so
the number climbs rather than jumping at the end.

### Step 4 — Review the candidates

```
GET /api/v1/banking/scans/<scan_id>/candidates
```

```json
{
  "success": true, "message": "Candidates fetched successfully.",
  "data": [
    { "id": "93e6133b-…", "vendor_name": "Verizon Business",
      "category_guess": "8b1cb1c7-…", "category_guess_name": "Telecom",
      "cadence": "MONTHLY", "due_day": 15, "amount": "389.00",
      "occurrences": 12, "selected": true, "is_imported": false,
      "imported_bill": null },
    { "id": "dd869281-…", "vendor_name": "WeWork",
      "category_guess": "6d7aded1-…", "category_guess_name": "Commercial Rent",
      "cadence": "MONTHLY", "due_day": 1, "amount": "3200.00",
      "occurrences": 12, "selected": true, "is_imported": false,
      "imported_bill": null },
    { "id": "1ed7e508-…", "vendor_name": "Amazon Web Services",
      "category_guess": null, "category_guess_name": null,
      "cadence": "MONTHLY", "due_day": 14, "amount": "892.00",
      "occurrences": 9, "selected": true, "is_imported": false,
      "imported_bill": null },
    { "id": "7f5c116e-…", "vendor_name": "Con Edison",
      "category_guess": null, "category_guess_name": null,
      "cadence": "MONTHLY", "due_day": 22, "amount": "226.25",
      "occurrences": 8, "selected": true, "is_imported": false,
      "imported_bill": null }
  ]
}
```

**Ordered most-confident first** (highest `occurrences`), which is the order to
render. `occurrences` is the *"12 occurrences — confirmed pattern"* badge.

`category_guess` is **best-effort and often `null`** — the user picks. Never
block import on it.

`due_day` is a day-of-month for monthly and quarterly cadences, and an **ISO
weekday (1–7)** for weekly.

`amount` is the cluster **median**, so a bill that varies month to month (Con
Edison above) reports a representative figure rather than the latest one.

### Step 5 — Import

```
POST /api/v1/banking/scans/<scan_id>/import
```

Everything: `{ "all": true }` — the *"Add All 17 Bills"* button.
A selection: `{ "candidate_ids": ["93e6133b-…", "dd869281-…"] }`.

**201:**

```json
{
  "success": true, "message": "Imported 4 bill(s), skipped 0.",
  "data": {
    "scan_id": "46fdcd18-…", "imported_count": 4, "skipped_count": 0,
    "imported": [
      { "candidate_id": "93e6133b-…", "vendor_name": "Verizon Business",
        "bill_id": "60d15da8-…", "vendor_id": "a93b7ca4-…",
        "amount": "389.00", "anchor_date": "2026-08-15" }
    ],
    "skipped": []
  }
}
```

Each import creates a **Vendor** (`source: IMPORT`) and a **Bill**
(`source: DETECTED`, `autopay_mode: REMIND`) and seeds its occurrences, so the
bills screen has rows immediately.

**`anchor_date` is always in the future.** A bill detected on the 15th imports
anchored to the *next* 15th, so it does not immediately read `OVERDUE` for a
cycle the user already paid by hand.

An existing vendor with the same name is reused rather than duplicated.

#### Re-posting is safe

```json
{ "success": true, "message": "Imported 0 bill(s), skipped 4.",
  "data": { "imported_count": 0, "skipped_count": 4, "imported": [],
    "skipped": [
      { "candidate_id": "93e6133b-…", "vendor_name": "Verizon Business",
        "bill_id": "60d15da8-…", "reason": "already_imported" }
    ] } }
```

Still **201**, nothing duplicated, and every skip names the bill it already
created. Safe to retry on a flaky connection.

You can also send an **`Idempotency-Key`** header; a repeat with the same key
replays the first response verbatim.

### Step 6 — The done screen

```
GET /api/v1/banking/onboarding-summary
```

```json
{
  "success": true, "message": "Onboarding summary fetched successfully.",
  "data": {
    "connection": {
      "connection_id": "de32fce1-…", "institution_name": "Chase Bank",
      "institution_logo": "", "status": "ACTIVE",
      "connected_at": "2026-07-28T12:06:01.057173Z", "account_count": 2,
      "funding_account": { "account_id": "9b607149-…",
        "name": "Chase Business Checking", "mask": "4821",
        "display": "Chase Business Checking ****4821" }
    },
    "detection": { "detected": 4, "imported": 4, "pending": 0 },
    "bills": { "total_due_this_month": "0.00", "overdue_count": 0,
      "due_count": 0, "upcoming_count": 12 },
    "rail_readiness": { "total_vendors": 4, "network_matched": 0,
      "ach_captured": 0, "check_ready": 0, "needs_details": 4 }
  }
}
```

`connection` is **`null`** when nothing is linked — check before dereferencing.

`bills` comes from the same selector as `GET /bills/summary`, so the two
screens cannot disagree.

**`rail_readiness.needs_details` is the number that matters after import.**
Imported vendors arrive with no payment method, so they cannot actually be
paid yet. That count is the user's next task — sending them to add ACH or
check details is the natural follow-on from onboarding.

---

## 3. Managing connections

### 3.1 List

```
GET /api/v1/banking/connections
```

Returns every connection including `DISCONNECTED` ones, each with its
`accounts` array (same shape as step 2).

### 3.2 Detail

```
GET /api/v1/banking/connections/<connection_id>
```

### 3.3 Disconnect

```
DELETE /api/v1/banking/connections/<connection_id>
```

**200** with the updated connection: `status` becomes `DISCONNECTED` and every
account's `is_default_funding_source` is cleared, so nothing can draw on a dead
link.

> ⚠️ **Blocked while payments are in flight.** If any payment is `SCHEDULED`,
> `PENDING` or `PROCESSING`, this returns **400** — removing the funding source
> mid-flight would strand the payment.
>
> ```json
> { "success": false, "message": "Validation failed.",
>   "errors": { "connection": ["Cannot disconnect while 1 payment(s) are in flight. Cancel or wait for them to settle first."] } }
> ```
>
> Surface that message; the user needs to know what to do about it.

Note this is **200 with a body**, not 204 — the vendor delete endpoint returns
204, so don't share a handler.

---

## 4. Funding accounts

### 4.1 List

```
GET /api/v1/banking/accounts?connection_id=<optional>
```

Only accounts on **ACTIVE** connections. Sorted funding-source first.

### 4.2 Change the funding source

```
POST /api/v1/banking/accounts    { "account_id": "578e047d-…" }
```

**200** with the updated account. Atomic — exactly one account is the funding
source at a time.

---

## 5. Re-scanning

```
POST /api/v1/banking/scans    { "connection_id": "…", "months": 24 }
```

**202** with a scan object; poll it as in step 3.

`months` is optional, 1–24, default 24. Values above 24 are clamped. 24
months is the product decision (2026-08-25), matching the designs; it
replaced an earlier cap of 12.

Re-scanning an existing connection **does not duplicate candidates** — the
detector recognises patterns it has already recorded and `detected_count`
reports the scan's full total, not just what this pass added.

---

## 6. ABA routing validation

Used by the vendor ACH form rather than onboarding, but it lives here.

```
POST /api/v1/banking/routing/validate    { "routing_number": "021000021" }
```

```json
{ "success": true, "message": "Valid – JPMorgan Chase Bank (ABA verified)",
  "data": { "valid": true, "bank_name": "JPMorgan Chase Bank",
    "aba_verified": true, "bank_known": true,
    "message": "Valid – JPMorgan Chase Bank (ABA verified)" } }
```

> ⚠️ **An invalid number still returns HTTP 200** with `success: true` and
> `data.valid: false`. The request succeeded; the number didn't. **Branch on
> `data.valid`.**

`valid` and `bank_known` are independent — a number can pass the checksum but
be absent from the bank directory. Still valid, just no name to show.

Formatting is tolerated (`026-009-593`). The number is write-only and never
echoed back, masked input is rejected, and the endpoint is capped at 30/min.

Passing the checksum proves the number is **well-formed**, not that the account
exists.

---

## 7. Vocabulary

| Enum | Values |
|---|---|
| connection `status` | `ACTIVE` · `DISCONNECTED` · `ERROR` |
| scan `status` | `RUNNING` · `DONE` · `FAILED` |
| `account_type` | `CHECKING` · `SAVINGS` |
| candidate `cadence` | `MONTHLY` · `QUARTERLY` · `WEEKLY` · `ONE_TIME` |

Money is a decimal string, USD. Dates are `YYYY-MM-DD`, timestamps ISO-8601
UTC, ids UUIDs.

---

## 8. Errors

| Status | Meaning |
|---|---|
| 400 | validation — read `errors`; also the disconnect-blocked case |
| 401 | missing or expired token |
| 409 | `Idempotency-Key` reused with a different body |
| 429 | routing validation rate limit |

A connection, scan or candidate in the **URL** that is missing or belongs to
another user returns **404**. An unknown id in the **request body** (e.g.
`connection_id` on `POST /scans`, `account_id` on `POST /accounts`) is a
**400** on that field, because the body is what was wrong.

---

## 9. Testing against the mock

With `BANK_DATA_PROVIDER=mock` (the default in dev), the flow runs end to end
with no real bank.

**Pick an institution via the public token** — it just needs to contain the
name:

| `public_token` | Institution |
|---|---|
| `public-mock-chase` | Chase Bank ****4821 |
| `public-mock-bofa` | Bank of America ****7734 |
| `public-mock-wellsfargo` | Wells Fargo ****1192 |
| `public-mock-usbank` | U.S. Bank ****5580 |

The mock returns a fixed 12-month history of **46 transactions** that always
detects the same **four** candidates. The scan still reports
`months_history: 24`, the window it asked for; the mock simply has no older
data. Real Plaid serves the full 24 months.

| Vendor | Amount | Cadence | Day | Occurrences |
|---|---|---|---|---|
| Verizon Business | 389.00 | MONTHLY | 15 | 12 |
| WeWork | 3200.00 | MONTHLY | 1 | 12 |
| Amazon Web Services | 892.00 | MONTHLY | 14 | 9 |
| Con Edison | 226.25 | MONTHLY | 22 | 8 |

It also includes cases the detector must **reject**, so you can verify your UI
never shows them: a vendor appearing only twice (below the 3-occurrence floor)
and several one-off purchases.

Con Edison's amounts drift month to month on purpose — its `226.25` is the
median, which is why it is not a round number.

---

## 10. Quick reference

| Method | Path | Returns |
|---|---|---|
| `POST` | `/banking/link/token` | link token |
| `POST` | `/banking/link/exchange` | 201 · connection + accounts + started scan |
| `GET` | `/banking/connections` | connection list |
| `GET` | `/banking/connections/<id>` | one connection |
| `DELETE` | `/banking/connections/<id>` | 200 · disconnected, or 400 if payments in flight |
| `GET` | `/banking/accounts` | funding accounts, masks only |
| `POST` | `/banking/accounts` | set the default funding source |
| `POST` | `/banking/scans` | 202 · new scan |
| `GET` | `/banking/scans/<id>` | scan status — poll this |
| `GET` | `/banking/scans/<id>/candidates` | detected candidates |
| `POST` | `/banking/scans/<id>/import` | 201 · import report |
| `GET` | `/banking/onboarding-summary` | the done screen |
| `POST` | `/banking/routing/validate` | ABA check — branch on `data.valid` |
