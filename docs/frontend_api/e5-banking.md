# E5 — Banking & Onboarding

Link a bank, scan 12 months of transactions, review the bills Swayp found,
import them.

← [Index](README.md) · Prev: [E4](e4-bills.md) · Next: [E6 Payments](e6-payments.md)

**This is the fastest path to real data.** One link produces four vendors and
four bills with schedules, so build it before the screens that display them.

---

## 1. The flow

```
POST banking/link/token/              → link_token for the bank widget
   ↓  user picks their bank
POST banking/link/exchange/           → connection + accounts, scan auto-starts
   ↓
GET  banking/scans/<id>/              → poll until is_complete
   ↓
GET  banking/scans/<id>/candidates/   → what Swayp found
   ↓  user ticks the ones to keep
POST banking/scans/<id>/import/       → bills + vendors created
   ↓
GET  banking/onboarding-summary/      → the "here's what we set up" screen
```

---

## 2. Link and exchange

```
POST /api/v1/banking/link/token/     { }
```

Returns a `link_token` for the bank widget.

```
POST /api/v1/banking/link/exchange/
```

```json
{ "public_token": "public-mock-chase", "consent_accepted": true }
```

**`consent_accepted` is required** — omitting it is a 400. Linking a bank
records a consent timestamp, so the user has to actually agree.

**201** returns the connection, its accounts (masked), and a `scan` object —
**the scan starts automatically**, you do not kick it off separately.

```json
{ "id": "…", "institution_name": "Chase Bank", "status": "ACTIVE",
  "accounts": [
    { "id": "…", "name": "Chase Business Checking", "mask": "4821",
      "display": "Chase Business Checking ****4821",
      "account_type": "CHECKING", "is_default_funding_source": true,
      "available_balance": "41200.00", "current_balance": "41200.00",
      "balance_as_of": "2026-07-29T…" } ],
  "scan": { "id": "f1550c32-…", "status": "RUNNING", "months_history": 12,
            "transactions_scanned": 0, "detected_count": 0,
            "progress": { "is_complete": false, "thin_history": false } } }
```

### Without a real bank

Put the institution in the token: `public-mock-chase`, `public-mock-bofa`,
`public-mock-wellsfargo`, `public-mock-usbank`. Every link yields the same
12-month history and the same four detected bills.

### Only masks, ever

`mask`, `display` and the balances are all you get. Account and routing
numbers are never returned, never stored, and the bank access token is not
exposed through any endpoint. Don't design a screen that shows a full number.

---

## 3. Polling the scan

```
GET /api/v1/banking/scans/<scan_id>/
```

```json
{ "id": "a2f1c210-…", "status": "RUNNING", "months_history": 12,
  "transactions_scanned": 0, "detected_count": 0,
  "error_message": "", "completed_at": null,
  "progress": { "is_complete": false, "thin_history": false } }
```

**Poll on `progress.is_complete`, not on `status`.** `transactions_scanned`
and `detected_count` rise while it runs, so you can show real progress rather
than a spinner.

`thin_history: true` means under 180 days of transactions — Swayp found less
than it would like. Degrade the copy ("we found what we could") rather than
treating it as a failure.

A failed scan sets `status` and fills `error_message`; show that text.

---

## 4. Review the candidates

```
GET /api/v1/banking/scans/<scan_id>/candidates/
```

Each candidate is a detected recurring payment — vendor name, amount,
cadence, confidence, and the transactions behind it. This is a review screen:
the user unticks anything wrong before importing.

## 5. Import

```
POST /api/v1/banking/scans/<scan_id>/import/
```

```json
{ "candidate_ids": ["…", "…"] }
```

**201**, with counts of what was created and a `skipped` array explaining
anything that wasn't.

⚠️ **Re-POSTing is a no-op, not an error.** It returns 201 with everything in
`skipped`. That is the idempotent path, so a double-tap is safe — read
`skipped` before showing "nothing imported" as a failure.

Send `Idempotency-Key` as well; see [E1](e1-foundations.md).

---

## 6. Connections and accounts

```
GET    /api/v1/banking/connections/
GET    /api/v1/banking/connections/<id>/
DELETE /api/v1/banking/connections/<id>/     ← disconnect
GET    /api/v1/banking/accounts/
POST   /api/v1/banking/accounts/             ← set the default funding source
```

### Disconnect is guarded ⚠️

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "connection": "…payments in flight…" } }
```

A connection with a payment still moving **cannot** be disconnected — 400.
Money is already in motion against that account. Surface the message and
offer to cancel the payments first.

### The bank limit is a plan limit

Connecting past `bank_limit` returns **402**, not 403:

```json
{ "success": false,
  "message": "Your Founding plan allows 1 connected bank. Upgrade to add more." }
```

Show an upgrade prompt. Founding allows 1; Standard and Enterprise are
unlimited. See [E9](e9-billing.md).

Disconnecting frees the slot immediately — the count is derived from live
connections, so `GET /billing/allowances/` and this gate can never disagree.

---

## 7. The onboarding summary screen

```
GET /api/v1/banking/onboarding-summary/
```

```json
{
  "connection": { "connection_id": "…", "institution_name": "Chase Bank",
    "status": "ACTIVE", "account_count": 1,
    "funding_account": { "account_id": "…", "name": "Chase Business Checking",
                         "mask": "4821",
                         "display": "Chase Business Checking ****4821" } },
  "detection": { "detected": 0, "imported": 0, "pending": 0 },
  "bills": { "total_due_this_month": "0.00", "overdue_count": 0,
             "due_count": 0, "upcoming_count": 1 },
  "rail_readiness": { "total_vendors": 1, "network_matched": 0,
                      "ach_captured": 1 }
}
```

One call for the whole "here's what we set up" screen. The numbers reconcile
with [`bills/summary/`](e4-bills.md) and
[`vendors/summary/`](e3-vendors.md) — same data, one aggregate query set.

`rail_readiness` tells you how many vendors can actually be paid: a vendor
with no payment method can't be, and this is where you nudge the user to add
one.

---

## 8. Order to build

1. **Link → exchange** with a mock token. You now have data.
2. **Scan polling** with real progress numbers.
3. **Candidate review + import.**
4. **Onboarding summary.**
5. **Connections/accounts management** — later; it's a settings screen.
