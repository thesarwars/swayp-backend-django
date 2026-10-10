# E9 — Billing & Subscriptions

Plans, the trial, card collection, allowances, per-transaction fees, and the
invoice.

← [Index](README.md) · Prev: [E8](e8-dashboard-reports.md) · Next: [E10 Teams](e10-teams.md)

Full reference: [Billing API](../billing-api-documentation.md) ·
Setup: Stripe Billing

---

## 1. Ask whether money is being collected — don't assume

Stripe is wired, but whether it charges is configuration. Ask with a read
that creates nothing:

```
GET /api/v1/billing/config
```

```json
{ "collects_money": true, "publishable_key": "pk_test_…" }
```

Only when you are about to show the card form, open a SetupIntent:

```
POST /api/v1/billing/payment-method/setup
```

```json
{ "client_secret": "seti_…_secret_…",
  "publishable_key": "pk_test_…",
  "collects_money": true }
```

Every `setup` call creates a SetupIntent at Stripe, so don't use it just to
learn `collects_money`.

**`collects_money: false`** means no processor is configured — entitlements
are recorded and nothing is charged. **Skip the card form entirely** rather
than mounting one that can never work.

The request and response shapes are identical either way, so one build serves
both.

## 2. `limit: null` means unlimited, not zero

```json
"BANKS": { "limit": null, "unlimited": true, "used": 1, "remaining": null }
```

Branch on `unlimited`. `!limit` cannot tell `null` from `0`, and those are
opposite answers.

## 3. 402 is an upgrade, 403 is a role

Plan ceilings answer **402**, never 403 — the request was authorised, the plan
is just full. It carries `message` only, written to be shown verbatim.

```json
{ "success": false,
  "message": "Your Founding plan allows 1 connected bank. Upgrade to add more." }
```

**402 arrives from the endpoint that performs the action**, never from
`/billing/`. Handle it globally.

| Action | Endpoint | Ceiling |
|---|---|---|
| Connect a bank | `POST banking/link/exchange` | `bank_limit` |
| Invite a member | `POST teams/invite` | `seat_limit` |

---

## 4. Pricing screen

```
GET /api/v1/billing/plans
```

```json
[
  { "code": "FOUNDING", "name": "Founding", "monthly_price": "49.00",
    "seat_limit": 3, "bank_limit": 1,
    "unlimited_seats": false, "unlimited_banks": false,
    "free_checks_per_month": 2, "included_entities": 1,
    "price_locked": true, "trial_days": 0 },
  { "code": "STANDARD", "name": "Standard", "monthly_price": "99.00",
    "seat_limit": 10, "bank_limit": null,
    "unlimited_seats": false, "unlimited_banks": true,
    "free_checks_per_month": 5, "included_entities": 1,
    "price_locked": false, "trial_days": 14 },
  { "code": "ENTERPRISE", "name": "Enterprise", "monthly_price": "299.00",
    "seat_limit": null, "bank_limit": null,
    "unlimited_seats": true, "unlimited_banks": true,
    "free_checks_per_month": 5, "included_entities": 3,
    "price_locked": false, "trial_days": 0 }
]
```

Sorted by price — array order is display order.

⚠️ **The design shows four plans including Solo $29, and "unlimited team
members" on every one. Both are wrong.** BRD §6.2 is the source of truth:
three plans, seats 3 / 10 / unlimited. Build from this response.

⚠️ **The Founder card says "first 100" in its body and "first 500" in its
badge.** 500 is correct.

**`price_locked: true` is a property of the plan, not the customer.** It means
Founding *offers* a lock. Whether *this* customer has one is
`subscription.locked_price`.

**Seat copy:** Founding's 3 seats **include the owner**, so a new customer can
invite 2. Write "3 users", never "3 teammates".

---

## 5. Subscribe, with or without a card

```
POST /api/v1/billing/subscription
```

```json
{ "plan": "STANDARD", "payment_method_id": "pm_…" }
```

`payment_method_id` comes from Stripe Elements after confirming the SetupIntent
from §1. **The card never reaches Swayp.**

**201** returns the subscription — and possibly one more step:

```json
{ "id": "…", "plan": { "…": "…" }, "status": "ACTIVE",
  "period_start": "2026-07-29", "period_end": "2026-08-29",
  "locked_price": "49.00", "effective_price": "49.00",
  "provider_status": "incomplete",
  "client_secret": "pi_…_secret_…",
  "trial_end": null, "is_trialing": false, "trial_days_remaining": null }
```

⚠️ **A non-empty `client_secret` means 3-D Secure. Confirm it with Stripe.js.**
Skipping it leaves the subscription unpaid at Stripe even though Swayp shows
`ACTIVE` — the entitlement is granted immediately so the customer isn't locked
out mid-prompt, but the money has not moved.

**Declined card → 400**, not 402 — no upgrade fixes a bad card:

```json
{ "errors": { "payment_method_id": "Your card was declined." } }
```

**Provider unreachable → 503**, "your card has not been charged, try again".

### The 14-day trial

Standard has `trial_days: 14`; Founding and Enterprise have 0 — the Founder
rate is a limited spot claimed by paying ("Pay $49 and claim my spot"), so it
doesn't trial.

**A trial needs no card.** Subscribe with no `payment_method_id` and Stripe
returns `trialing` with nothing to confirm — that's what makes "no card
needed" true.

`status` stays **`ACTIVE`** throughout: a trial is a promise not to charge
yet, not a reduced product, and allowances are the plan's full allowances. So
read the trial from these instead:

| Field | Meaning |
|---|---|
| `is_trialing` | inside the free window |
| `trial_days_remaining` | `14`, counting down; **`0`** when lapsed; **`null`** when there was never a trial |

`null` and `0` are different — a banner must tell them apart.

**One trial per account.** An account that has subscribed before (even one
that cancelled) gets no second trial. `GET /billing/plans` says what **this
account** would get by subscribing now:

| Field | Meaning |
|---|---|
| `trial_eligible` | Subscribing starts the plan's trial. `false` for a returning account, or a plan with no trial. |
| `lock_available` | Subscribing locks this plan's price (Founding). `false` once the 500 spots are gone. |
| `founding_spots_remaining` | Founding spots left; `null` on other plans |

Show the "14-day free trial" badge and the "claim my spot" button from these,
not from `trial_days` and `price_locked`, which describe the plan in general.

### Change plan, cancel

```
PATCH  /api/v1/billing/subscription   { "plan": "ENTERPRISE" }
DELETE /api/v1/billing/subscription
```

Cycle boundaries are kept and **there is no proration** — the change takes
effect at the new price with no credit. Don't promise one.

**A plan too small for the account is refused.** Moving to a plan with fewer
seats or banks than the account uses now is a **402**, and nothing changes:

```json
{ "success": false,
  "message": "This plan is too small for the account: 3 connected banks in use, Founding allows 1. Remove the extra ones first, or choose a bigger plan." }
```

Pending invitations count as seats, so revoke spare invitations before
downgrading. The check covers seats and banks; checks reset monthly, so a
smaller check allowance never blocks a change. `PATCH` with no subscription is
a 400. Warn before the user picks a smaller plan, but rely on this answer.

**Cancelling keeps the paid period.** `DELETE` doesn't end the plan at once:
it stays `ACTIVE`, with every allowance, until `cancels_on`, then ends. That
date is the end of the paid month, or the trial's end during a trial.
Nothing is refunded, because nothing is lost. The response has:

| Field | Meaning |
|---|---|
| `cancel_pending` | `true` once cancelled |
| `cancels_on` | The last day of access; `null` when nothing is pending |

Show "Your plan ends on <date>" and offer **Undo**:

```
POST /api/v1/billing/subscription/resume
```

That withdraws the cancellation, and the plan continues as before. Without a
pending cancellation it's a 400. While a cancellation is pending the account
still holds its plan, so subscribing to another is refused; use `PATCH` to
change plans. If the payment provider can't be reached, cancel and resume
fail with a message to try again, rather than leave the customer billed after
they were told the plan ends.

⚠️ **Leaving Founding gives up the price lock permanently.** Warn when
`locked_price !== null`.

### Past due

When a charge fails, `status` becomes `PAST_DUE` and `past_due` is `true`.
**The plan stays in force**: limits, seats and banks are unchanged, and Stripe
retries the charge. Show a banner and send the owner to replace the card
(`POST /billing/payment-method`, §5b). A successful retry, or a new card,
returns it to `ACTIVE`. If Stripe gives up, the subscription ends
(`CANCELLED`). While past due the account can't open a second subscription;
`POST` is a 400.

**Writes are owner-only.** `POST`/`PATCH`/`DELETE` need `manage_billing` —
**not even an admin** has it, because a plan change changes what the owner is
charged. Reads are open to the whole team. Gate the screen on
[`teams/me`](e10-teams.md) capabilities.

---

## 5b. Card on file

```
GET  /api/v1/billing/payment-method
POST /api/v1/billing/payment-method     { "payment_method_id": "pm_…" }
```

`GET` returns the default card, or `null` when there is none (or nothing
collects money, as on the mock):

```json
{ "brand": "visa", "last4": "4242", "exp_month": 12, "exp_year": 2030 }
```

To **replace** it: get a SetupIntent from `POST billing/payment-method/setup`,
confirm the card with Stripe's SDK, then `POST` the resulting
`payment_method_id` here. The card goes straight to Stripe and never to
Swayp. The new card becomes the default for future charges. **If the
subscription is past due, the unpaid invoice is charged to it at once**, and
on success the subscription returns to `ACTIVE`. A declined card is a 400 on
`errors.payment_method_id`. With no subscription it's a 400 (choose a plan
first). On the mock there's nothing to collect, so `POST` is a 400 too. Owner
only, like the other billing writes.

## 6. Which price to display

| Field | Means |
|---|---|
| `plan.monthly_price` | today's list price |
| `locked_price` | what this customer locked, or `null` |
| **`effective_price`** | **what they actually pay** |

**Always render `effective_price`.**

---

## 7. Allowances

```
GET /api/v1/billing/allowances
```

```json
{ "CHECKS": { "limit": 2, "unlimited": false, "used": 0, "remaining": 2 },
  "SEATS":  { "limit": 3, "unlimited": false, "used": 2, "remaining": 1 },
  "BANKS":  { "limit": 1, "unlimited": false, "used": 1, "remaining": 0 } }
```

| Kind | Resets? | At the limit |
|---|---|---|
| `CHECKS` | **yes**, at `period_end` | **never blocks** — bills $2.99 |
| `SEATS` | no | 402 on invite |
| `BANKS` | no | 402 on bank connect |

**Only show "resets on `period_end`" against CHECKS.**

`used` can exceed `limit` for CHECKS — that is an overage. `remaining` floors
at 0, so the overage count is `used - limit`, never `-remaining`.

These numbers are counted from the same rows the gates check, so when
`remaining` is 0 the button really will 402. **Refetch after any invite,
removal, connect or disconnect.**

---

## 8. Fees

| Rail | Requested with | Fee | Guaranteed? |
|---|---|---|---|
| Standard ACH | `rail: "ACH_STANDARD"` | free | — |
| Same-day ACH | `rail: "ACH_SAMEDAY"` | **$4.99** before cutoff only | yes |
| Standard check | `rail: "CHECK"` | free to allotment, then **$2.99** | no |
| Expedited check | `rail: "CHECK"` + `expedited: true` | **$8.99** always | yes |

All chosen on [`POST /payments/`](e6-payments.md). Fees are charged **at
send**, not at arrival.

⚠️ **After the 11:59 PM Eastern cutoff, same-day is withdrawn, not sold.** No
fee, no row. Hide the option rather than offering something undeliverable.

```
GET /api/v1/billing/fees?page=1&pageSize=20&state=&from_date=&to_date=
```

```json
{ "data": [
    { "id": "ec0e143a-…", "kind": "SAME_DAY_ACH", "amount": "4.99",
      "state": "REFUNDED", "payment_id": "5b1f…",
      "payment_reference": "SWP-20260801-0000",
      "guaranteed_arrival": "2026-07-29",
      "refunded_at": "2026-07-29T08:54:46.555733Z",
      "refund_reason": "Delivery guarantee missed",
      "created_at": "2026-07-29T08:54:46.518961Z" } ],
  "pagination": { "page": 1, "pageSize": 20, "totalPages": 1,
                  "totalItems": 1, "hasNext": false, "hasPrevious": false } }
```

- Paged like every other list (`page`, `pageSize` ≤ 100), newest first.
- Filters apply **before** paging: `state` (`PENDING`, `BILLED`, `REFUNDED`)
  and the day charged, `from_date` / `to_date` (`YYYY-MM-DD`, both
  inclusive). An unknown state or a backwards range is a 400.
- `payment_id` opens the payment and its receipt
  ([E6](e6-payments.md)): `GET /payments/<payment_id>`.

### Guarantee refunds

Same-day ACH and expedited check buy a delivery promise. Missing it refunds
**automatically** — no support ticket.

**On refund, `amount` does not change — `state` does.** Don't sum `amount` to
get what is owed; use the invoice.

⚠️ **Never compute "this looks late, so it must be refunded" client-side.**
The guarantee is judged at *arrival*, so a fee can sit `PENDING` past its
`guaranteed_arrival` and still refund later. Poll the ledger or wait for the
notification (`type: "PAYMENT"`, `fee_charge_id` in `metadata`).

A **check overage is never refunded for slowness** — it bought no promise,
which is why its `guaranteed_arrival` is `null`.

---

## 9. Invoice preview

```
GET /api/v1/billing/invoice
```

```json
{ "plan": "ENTERPRISE",
  "period_start": "2026-07-29", "period_end": "2026-08-29",
  "lines": [
    { "kind": "SUBSCRIPTION", "description": "Enterprise plan",
      "quantity": 1, "unit_price": "299.00", "total": "299.00" },
    { "kind": "EXTRA_ENTITY", "description": "Extra entity",
      "quantity": 2, "unit_price": "79.00", "total": "158.00" },
    { "kind": "SAME_DAY_ACH",
      "description": "Same-day ACH — SWP-20260801-0000 (refunded)",
      "quantity": 1, "unit_price": "4.99", "total": "0.00" }
  ],
  "subtotal": "608.99", "currency": "USD", "next_charge_date": "2026-08-29" }
```

Line order is fixed and safe to render as-is: plan, add-ons by kind, then fees
oldest-first.

Every line also carries `state`, `fee_charge_id`, `payment_reference` and
`created_at`. On fee lines they are the fee's: `state` is `PENDING` or
`REFUNDED`, so branch on it, not on `total == 0`. On plan and add-on lines all
four are `null`.

`next_charge_date` is when the card is next billed: `trial_end` during a
trial, otherwise `period_end`. It is `null` when the plan is cancelling or the
deployment collects no money. Show it as the billing date; `period_end` is
when the allowances reset.


### Render `total`, not `unit_price` ⚠️

Look at the refunded line: `unit_price: "4.99"`, `total: "0.00"`.

The line stays deliberately — dropping it would hide that Swayp honoured its
guarantee. Strike it through or label it "refunded". Render `unit_price` and
the invoice appears not to add up. `subtotal` is the sum of `total`.

### Past invoices

```
GET /api/v1/billing/invoices?limit=20&starting_after=
```

What the payment processor actually billed, newest first:

```json
{ "success": true, "message": "Invoices fetched successfully.",
  "data": [
    { "id": "in_1Q…", "number": "SW-0001", "status": "paid",
      "total": "49.00", "currency": "usd",
      "created": "2026-09-01T00:00:00Z",
      "period_start": "2026-08-01T00:00:00Z", "period_end": "2026-09-01T00:00:00Z",
      "paid_at": "2026-09-01T00:05:00Z",
      "pdf_url": "https://pay.stripe.com/invoice/…/pdf",
      "hosted_url": "https://invoice.stripe.com/i/…" } ],
  "next_cursor": "in_1Q…" }
```

- **Cursor paged, not page numbers:** the processor pages by cursor. For the
  next page send `starting_after=<next_cursor>`. `next_cursor` is `null` on
  the last page. `limit` is 1–100, default 20.
- `status`: `paid`, `open` (not yet paid; past due if the subscription is),
  `void`, `uncollectible`, `draft`.
- `pdf_url` downloads the invoice; `hosted_url` opens the processor's page
  for it, where an `open` one can also be paid.
- On a deployment that collects no money (`collects_money: false`, §1) the
  list is always empty. Show the empty state, not an error.

---

## 10. Enterprise add-ons

```
GET  /api/v1/billing/addons
POST /api/v1/billing/addons     { "kind": "EXTRA_ENTITY", "quantity": 2 }
```

| Kind | Price | Quantity |
|---|---|---|
| `EXTRA_ENTITY` | $79 | any — entities beyond the 3 included |
| `APPROVAL_WORKFLOW` | $99 | 1 only |
| `ERP_SYNC` | $149 | 1 only |
| `CUSTOM_SLA` | $199 | 1 only |

POST is an upsert; **`quantity: 0` removes** (200, `data: null`). There is no
DELETE.

⚠️ **`GET` returns `200 []` on a non-Enterprise plan, not an error.** An empty
array does *not* mean "hide the section" — gate on
`subscription.plan.code === "ENTERPRISE"`.

`unit_price` is captured **at sale time**, so an existing add-on may
legitimately differ from the table. Render the row's `unit_price`, never a
hardcoded list.

> **Approval workflow and ERP sync are sellable but inert** — E10-S4 is
> deferred. Buying them changes the invoice and nothing else.

---

## 11. Order to build

1. **Pricing page** — array order is display order.
2. **Card collection**, branched on `collects_money`.
3. **Subscribe**, confirming `client_secret` if present.
4. **Billing screen** — subscription + allowances, `effective_price`.
5. **Fee ledger** — refunded rows are a feature; show them.
6. **Invoice** — render `total`.
7. **Add-ons**, gated on the plan code.
