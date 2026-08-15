# Billing API Documentation

Plans, what each plan lets you do, the per-transaction fees, and the invoice
that adds it all up.

**Base URL:** `/api/v1/billing`
**Auth:** every endpoint requires `Authorization: Bearer <access_token>`.

Every response body below was captured from the running API.

Related: Payments API · [Banking API](banking-api-documentation.md) · [Frontend Guide](frontend-integration-guide.md)

---

## 1. Read this first

### 1.1 Whether a card is charged depends on configuration ⚠️

Stripe is wired. Whether it collects depends on one setting:

| | `POST /subscription/` |
|---|---|
| **mock** (default) | records the entitlement, charges nothing |
| **stripe** | creates a real customer and subscription, charges the card |

**Ask, do not assume.** `POST /billing/payment-method/setup/` returns
`collects_money`. When it is `false`, skip the card form entirely rather than
mounting one that can never work.

The request and response shapes are identical either way, so one client build
serves both. Full flow: Stripe Billing Setup.

### 1.2 402 means "upgrade", not "forbidden"

Plan ceilings answer **402 Payment Required**, never 403. The request was
authorised — the account simply needs a bigger plan.

That distinction is the whole point: **402 should render an upgrade prompt,
403 should render a permission error.** Treating them alike turns a sales
moment into a dead end.

```json
{ "success": false,
  "message": "Your Founding plan allows 1 connected bank. Upgrade to add more." }
```

Note the envelope: a 402 carries **`message` only, no `errors` object**. The
message is written to be shown to the user verbatim.

### 1.3 402 comes from other endpoints, not from Billing

The ceiling is enforced where the action happens, so plan out where you handle
it. Today the live one is:

| Action | Endpoint | Ceiling |
|---|---|---|
| Connect a bank | `POST /api/v1/banking/link/exchange` | `bank_limit` |
| Invite a team member | `POST /api/v1/teams/invite` | `seat_limit` |

**Handle 402 globally**, in whatever wraps fetch — it will appear on more
endpoints over time, and the message is always displayable as-is.

Don't confuse it with **403**, which means the caller's *role* forbids the
action. No upgrade fixes a 403. See [Teams API §1.3](teams-api-documentation.md).

### 1.4 `limit: null` means unlimited, not zero

```json
"BANKS": { "limit": null, "unlimited": true, "used": 1, "remaining": null }
```

`remaining` is `null` for unlimited too. **Read `unlimited` and branch on it**
rather than testing `limit` for falsiness — `null` and `0` are very different
answers and `!limit` cannot tell them apart.

### 1.5 Metered resets, capacity does not

Checks are **metered**: consumed over a cycle, reset at renewal, and going over
never blocks a send — it bills $2.99.

Seats and banks are **capacity**: a standing ceiling checked at the moment of
the add. They do not reset, because the banks you connected last month are
still connected this month.

So: **only show "resets on <period_end>" against CHECKS.** Saying it about
seats or banks would be a lie.

The reset is real: a nightly job rolls the cycle, and the check counter
comes back to 0 with it.

---

## 2. The three plans

```
GET /api/v1/billing/plans
```

**200:**

```json
{
  "success": true,
  "message": "Plans fetched successfully.",
  "data": [
    {
      "code": "FOUNDING",
      "name": "Founding",
      "monthly_price": "49.00",
      "seat_limit": 3,
      "bank_limit": 1,
      "unlimited_seats": false,
      "unlimited_banks": false,
      "free_checks_per_month": 2,
      "included_entities": 1,
      "price_locked": true
    },
    {
      "code": "STANDARD",
      "name": "Standard",
      "monthly_price": "99.00",
      "seat_limit": 10,
      "bank_limit": null,
      "unlimited_seats": false,
      "unlimited_banks": true,
      "free_checks_per_month": 5,
      "included_entities": 1,
      "price_locked": false
    },
    {
      "code": "ENTERPRISE",
      "name": "Enterprise",
      "monthly_price": "299.00",
      "seat_limit": null,
      "bank_limit": null,
      "unlimited_seats": true,
      "unlimited_banks": true,
      "free_checks_per_month": 5,
      "included_entities": 3,
      "price_locked": false
    }
  ]
}
```

Sorted by price ascending, so the array order is the pricing-page order.

`unlimited_seats` / `unlimited_banks` are conveniences over the `null` check
from §1.4 — use them for the "Unlimited" pill.

**`price_locked: true` is a property of the plan, not of the customer.** It
means Founding *offers* a lock. Whether a given customer *has* one is
`subscription.locked_price`.

---

## 3. Subscription

One endpoint, four verbs.

> **Collecting a card?** `POST /billing/payment-method/setup/` first, then
> send the resulting `payment_method_id` with the subscribe call. The card
> never reaches Swayp. See Stripe Billing Setup.

### 3.0 Reads are open to the team; writes are owner-only ⚠️

Anyone on the account can `GET` the subscription, allowances, invoice and
fees — seeing which plan you are on is not privileged.

`POST`, `PATCH` and `DELETE` require the **owner**. Not even an admin can
change the plan, because a plan change changes what the owner is charged.
Add-on writes are owner-only for the same reason: they add invoice lines.

**403** on a write means the caller is not the owner — render "ask the
account owner", never an upgrade prompt:

```json
{ "success": false, "message": "Your role does not allow this action." }
```

Gate the billing settings screen on `capabilities` containing
`manage_billing` from [`GET /teams/me/`](teams-api-documentation.md).

### 3.1 Read

```
GET /api/v1/billing/subscription
```

**200 — no subscription.** Not a 404: "this account has no subscription" is a
normal answer, and `data: null` is that answer.

```json
{ "success": true, "message": "Subscription fetched successfully.", "data": null }
```

**200 — subscribed:**

```json
{
  "success": true,
  "message": "Subscription fetched successfully.",
  "data": {
    "id": "2f6e31a2-3c05-438f-97a6-c0e1215b98cf",
    "plan": { "code": "FOUNDING", "name": "Founding", "monthly_price": "49.00", "…": "…" },
    "status": "ACTIVE",
    "period_start": "2026-07-29",
    "period_end": "2026-08-29",
    "locked_price": "49.00",
    "effective_price": "49.00",
    "created_at": "2026-07-29T08:54:46.430731Z"
  }
}
```

`plan` is the full nested object from §2 — no second request needed.

### 3.2 Subscribe

```
POST /api/v1/billing/subscription
```

```json
{ "plan": "FOUNDING" }
```

**201** — the body is the subscription object above.

**400 — already subscribed.** Change the plan instead; there is no "subscribe
again".

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "subscription": "This account already has an active subscription. Change the plan instead." } }
```

**400 — unknown plan:**

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "plan": ["\"PLATINUM\" is not a valid choice."] } }
```

### 3.3 Change plan

```
PATCH /api/v1/billing/subscription
```

```json
{ "plan": "ENTERPRISE" }
```

**200.** The cycle boundaries are kept — `period_start` and `period_end` do not
move. There is no proration today: the change takes effect immediately and the
next invoice is at the new price. Patching to the plan already held is a no-op
that returns 200.

**Leaving Founding gives up the price lock, and it does not come back.**
`locked_price` becomes `null`, and returning to Founding later is a fresh
signup subject to the 500-customer limit. Warn before the downgrade —
`locked_price !== null` is how you know there is something to lose.

### 3.4 Cancel

```
DELETE /api/v1/billing/subscription
```

**200.** The row is returned with `status: "CANCELLED"` — nothing is deleted,
so billing history survives. A subsequent `GET` returns `data: null`, because
"current subscription" means the active one.

---

## 4. The Founding price lock

The first 500 Founding customers keep $49/mo permanently. Three fields, and
they are easy to confuse:

| Field | Lives on | Means |
|---|---|---|
| `plan.monthly_price` | plan | today's list price |
| `locked_price` | subscription | the price this customer locked, or `null` |
| `effective_price` | subscription | **what they actually pay** |

**Bill against `effective_price`.** It is `locked_price` when there is one and
`monthly_price` otherwise, so it is correct in both cases and cannot drift when
list prices change.

`locked_price` is captured at signup. Customer 499 keeps $49 forever; customer
501 pays whatever Founding lists at that moment.

---

## 5. Allowances

```
GET /api/v1/billing/allowances
```

**200:**

```json
{
  "success": true,
  "message": "Allowances fetched successfully.",
  "data": {
    "CHECKS": { "limit": 2, "unlimited": false, "used": 0, "remaining": 2 },
    "SEATS":  { "limit": 3, "unlimited": false, "used": 0, "remaining": 3 },
    "BANKS":  { "limit": 1, "unlimited": false, "used": 1, "remaining": 0 }
  }
}
```

**400 — no subscription:**

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "subscription": "No active subscription." } }
```

### 5.1 What each row means

| Kind | Type | Resets | At the limit |
|---|---|---|---|
| `CHECKS` | metered | yes, at `period_end` | **never blocks** — bills $2.99 |
| `SEATS` | capacity | no | 402 on invite |
| `BANKS` | capacity | no | 402 on bank connect |

`used` can exceed `limit` for `CHECKS` — that is what an overage is.
`remaining` floors at 0 and never goes negative, so `used - limit` is the
overage count, not `-remaining`.

### 5.2 This screen and the 402 agree

`BANKS.used` is counted from the account's live bank connections and
`SEATS.used` from its team members — the same rows the gates check. So when
this shows `remaining: 0`, the button genuinely will 402, and removing a bank
or a member frees the slot on the next read with nothing to reconcile.

**The owner occupies a seat**, so a new account reads `SEATS used 1` before
anyone is invited. [Teams API §1.1](teams-api-documentation.md).

Practically: **refetch allowances after any connect, disconnect, invite or
removal** and trust the number.

---

## 6. Fees

Four things a payment can cost:

| Rail | Requested with | Fee | Guaranteed? |
|---|---|---|---|
| Standard ACH | `rail: "ACH_STANDARD"` | free, unlimited | — |
| Same-day ACH | `rail: "ACH_SAMEDAY"` | **$4.99**, before the daily cutoff only | yes |
| Standard check | `rail: "CHECK"` | free up to the plan allotment, then **$2.99** | no |
| Expedited check | `rail: "CHECK"` + `expedited: true` | **$8.99** on every plan | yes |

All four are chosen on `POST /api/v1/payments`. Fees are charged **at send**,
not at arrival, and appear in the ledger (§6.4) against the payment reference.

### 6.1 After the cutoff, same-day is not sold ⚠️

Past the daily bank cutoff (11:59 PM Eastern) the rail cannot deliver same-day,
so it is **withdrawn rather than sold and missed**. No fee is charged and no
row appears in the ledger.

**Hide or disable the same-day option after the cutoff** rather than offering
it and surprising the user. Cutoff semantics and the Eastern-time trap are in
Payments API §1.4.

### 6.2 Expedited check is not an overage

$8.99 applies on every plan and is never free, regardless of how much of the
check allotment is left. It is a separate product, not a penalty — a user with
5 free checks remaining still pays $8.99 to expedite one.

Request it with `expedited: true` on `POST /api/v1/payments`, **CHECK rail
only**. Any other rail is a 400 rather than a silent downgrade:

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "expedited": "Only check payments can be expedited." } }
```

The created payment echoes `"expedited": true` and carries a nearer
`estimated_arrival` — 2 business days of transit instead of 5. Full request
shape in Payments API §2.

### 6.3 `guaranteed_arrival` is the date the customer was shown

It equals the payment's `estimated_arrival` exactly. That matters for what you
render: **show the payment's `estimated_arrival` as the promise**, and the
refund in §7 will trigger on precisely the date the user was looking at.

### 6.4 The ledger

```
GET /api/v1/billing/fees
```

**200** — newest first:

```json
{
  "success": true,
  "message": "Fee charges fetched successfully.",
  "data": [
    {
      "id": "c474cc61-1a01-4e52-a38b-9d6c9bc7a210",
      "kind": "CHECK_OVERAGE",
      "amount": "2.99",
      "state": "PENDING",
      "payment_reference": "SWP-20260801-0003",
      "guaranteed_arrival": null,
      "refunded_at": null,
      "refund_reason": "",
      "created_at": "2026-07-29T08:54:46.537581Z"
    },
    {
      "id": "ec0e143a-0c38-48b6-a06d-9d55dfe6128c",
      "kind": "SAME_DAY_ACH",
      "amount": "4.99",
      "state": "PENDING",
      "payment_reference": "SWP-20260801-0000",
      "guaranteed_arrival": "2026-07-29",
      "refunded_at": null,
      "refund_reason": "",
      "created_at": "2026-07-29T08:54:46.518961Z"
    }
  ]
}
```

`payment_reference` is the same `SWP-…` string the payment receipt shows, so
a fee links straight back to what caused it.

`guaranteed_arrival` is `null` for `CHECK_OVERAGE` — see §7.

**States:** `PENDING` (accrued, not yet invoiced) → `BILLED` (on a closed
invoice) or `REFUNDED`. Fees are charged **when the payment is sent**, not when
it arrives — a mailed check has been printed whatever the bank does next.

---

## 7. Delivery-guarantee refunds

Same-day ACH and expedited check buy a delivery promise. Miss it and the fee
refunds **automatically** — it is the product commitment, not a goodwill
gesture, so no support ticket is involved.

### 7.1 When the judgement happens

**At arrival, not at send.** The refund cannot be decided when the payment
goes out: a mailed check has been printed, not delivered, and nothing is late
yet.

| Rail | Judged when |
|---|---|
| Same-day ACH | the processor confirms — for this rail, confirmation *is* arrival |
| Check | the processor's arrival webhook fires |

So a fee can sit `PENDING` well past its `guaranteed_arrival` and still refund
later. **Do not compute "this looks late, show it as refunded" client-side** —
poll the ledger, or wait for the notification.

The refunded row:

```json
{
  "id": "ec0e143a-0c38-48b6-a06d-9d55dfe6128c",
  "kind": "SAME_DAY_ACH",
  "amount": "4.99",
  "state": "REFUNDED",
  "payment_reference": "SWP-20260801-0000",
  "guaranteed_arrival": "2026-07-29",
  "refunded_at": "2026-07-29T08:54:46.555733Z",
  "refund_reason": "Delivery guarantee missed"
}
```

### 7.2 The amount does not change — the state does

`amount` stays `4.99` — the fee that *was* charged. What changed is `state`.
**Do not sum `amount` to get what is owed**; use the invoice (§9), where a
refunded fee totals `0.00`.

A **check overage is never refunded for slowness**. It bought no speed promise,
which is why its `guaranteed_arrival` is `null`.

The user is notified through the normal notifications feed, `type: "PAYMENT"`,
with `fee_charge_id` and `payment_id` in `metadata`. No polling needed.

---

## 8. Enterprise add-ons

```
GET  /api/v1/billing/addons
POST /api/v1/billing/addons
```

| Kind | Price | Quantity |
|---|---|---|
| `EXTRA_ENTITY` | $79.00 | any — entities beyond the 3 included |
| `APPROVAL_WORKFLOW` | $99.00 | 1 only |
| `ERP_SYNC` | $149.00 | 1 only |
| `CUSTOM_SLA` | $199.00 | 1 only |

**POST** is an upsert — it adds or updates, so there is no separate PUT:

```json
{ "kind": "EXTRA_ENTITY", "quantity": 2 }
```

**200:**

```json
{
  "success": true,
  "message": "Add-on saved.",
  "data": { "id": "df66a388-…", "kind": "EXTRA_ENTITY", "quantity": 2,
            "unit_price": "79.00", "line_total": "158.00" }
}
```

**Send `quantity: 0` to remove one.** There is no DELETE. The response is 200
with `data: null`:

```json
{ "success": true, "message": "Add-on removed.", "data": null }
```

**400 — POST on a non-Enterprise plan:**

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "plan": "Add-ons are available on the Enterprise plan only." } }
```

**GET does not reject** — on Founding or Standard it returns `200` with
`data: []`, since "no add-ons" is the truthful answer. So an empty array does
**not** tell you the section should be hidden. Gate the UI on
`subscription.plan.code === "ENTERPRISE"`, not on the array being empty, or
the user will find out only on submit.

**400 — quantity on a single-quantity kind:**

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "quantity": "ERP_SYNC is a single add-on; quantity must be 1." } }
```

`unit_price` is captured **at the moment of sale**. Enterprise is negotiated,
so a later rate change cannot silently reprice a signed contract — which means
an add-on's `unit_price` may legitimately differ from the table above. Always
render `unit_price` from the row, never from a hardcoded price list.

---

## 9. Invoice preview

```
GET /api/v1/billing/invoice
```

Everything the customer would be billed this cycle, derived on read. Nothing is
stored, so it is always current.

**200:**

```json
{
  "success": true,
  "message": "Invoice preview fetched successfully.",
  "data": {
    "subscription_id": "6252fb81-a34e-4843-bd7d-9b34cff58dac",
    "plan": "ENTERPRISE",
    "period_start": "2026-07-29",
    "period_end": "2026-08-29",
    "lines": [
      { "kind": "SUBSCRIPTION", "description": "Enterprise plan",
        "quantity": 1, "unit_price": "299.00", "total": "299.00" },
      { "kind": "ERP_SYNC", "description": "ERP sync",
        "quantity": 1, "unit_price": "149.00", "total": "149.00" },
      { "kind": "EXTRA_ENTITY", "description": "Extra entity",
        "quantity": 2, "unit_price": "79.00", "total": "158.00" },
      { "kind": "SAME_DAY_ACH",
        "description": "Same-day ACH — SWP-20260801-0000 (refunded)",
        "quantity": 1, "unit_price": "4.99", "total": "0.00" },
      { "kind": "CHECK_OVERAGE",
        "description": "Check overage — SWP-20260801-0003",
        "quantity": 1, "unit_price": "2.99", "total": "2.99" }
    ],
    "subtotal": "608.99",
    "currency": "USD"
  }
}
```

Line order is fixed and safe to render as-is: the plan first, then add-ons by
kind, then fees oldest-first.

### 9.1 A refunded fee shows at 0.00 rather than disappearing ⚠️

Look at the `SAME_DAY_ACH` line: `unit_price: "4.99"`, `total: "0.00"`,
`(refunded)` in the description.

That is deliberate. Dropping the line would hide the fact that Swayp honoured
its guarantee — the customer should see the promise being kept, not a fee that
quietly never existed.

**Render `total`, not `unit_price`.** A refunded line struck through, or
labelled "refunded", reads correctly; showing `unit_price` makes the invoice
appear not to add up.

### 9.2 `subtotal` is the sum of `total`

So it already excludes refunded fees. Don't recompute it from `unit_price`.

Only `PENDING` and `REFUNDED` fees appear. Once a fee is `BILLED` it belongs to
a closed invoice and drops out of the preview.

---

## 10. What to build, in order

1. **Pricing page** — `GET /plans/`. Array order is display order.
2. **Subscribe** — `POST /subscription/`. Handle the already-subscribed 400.
3. **Billing screen** — `GET /subscription/` + `GET /allowances/`. Show
   `effective_price`, not `monthly_price`.
4. **Global 402 handler** — one place, upgrade prompt, `message` verbatim.
5. **Fee history** — `GET /fees/`. Refunded rows are a feature; show them.
6. **Invoice** — `GET /invoice/`. Render `total`.
7. **Enterprise add-ons** — gate the section on the plan code.

---

## 11. Not built yet — do not design around these

| Gap | Impact |
|---|---|
| No proration | A mid-cycle plan change takes effect immediately at the new price with no credit for the unused part. Don't promise "you'll be credited". |
| Renewal rolls the cycle but collects nothing | A nightly job advances `period_start`/`period_end` and resets the free-check allowance, so entitlements are correct. It does **not** charge — that arrives with Stripe. Treat `period_end` as "when the allowance resets", not "when the card is billed". |
| Invoice history | Only the **current** cycle preview exists. There is no list of past invoices and no PDF. |
| Per-rail SLA thresholds | The guarantee compares against the arrival estimate at charge time. Explicit per-rail SLA windows are an open product question. |

---

## 12. Endpoint index

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/billing/plans` | the three tiers |
| GET | `/api/v1/billing/subscription` | current subscription, or `null` |
| POST | `/api/v1/billing/subscription` | subscribe |
| PATCH | `/api/v1/billing/subscription` | change plan |
| DELETE | `/api/v1/billing/subscription` | cancel |
| GET | `/api/v1/billing/allowances` | usage against each ceiling |
| GET | `/api/v1/billing/addons` | Enterprise add-ons |
| POST | `/api/v1/billing/addons` | add, update, or remove (`quantity: 0`) |
| GET | `/api/v1/billing/invoice` | current-cycle invoice preview |
| GET | `/api/v1/billing/fees` | per-transaction fee ledger |
