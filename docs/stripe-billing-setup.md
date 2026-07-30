# Stripe Billing — Setup and Go-Live

Subscription billing runs behind a provider interface. Switching from "record
the entitlement, charge nothing" to "actually collect the money" is a change to
`.env` and a redeploy — no code moves.

---

## 1. Configuration

Everything lives in `.env`, which is gitignored. **The secret key must never be
committed.**

```ini
SUBSCRIPTION_BILLING_PROVIDER=stripe      # or "mock"
STRIPE_SECRET_KEY=sk_test_...             # sk_live_... in production
STRIPE_PUBLISHABLE_KEY=pk_test_...        # pk_live_... in production
STRIPE_BILLING_WEBHOOK_SECRET=whsec_...
```

| Setting | Effect |
|---|---|
| `SUBSCRIPTION_BILLING_PROVIDER=mock` | **Default.** Subscriptions and fees are recorded; nothing is charged. |
| `SUBSCRIPTION_BILLING_PROVIDER=stripe` | Real customers, prices, subscriptions and invoice items. |

Selecting `stripe` with no `STRIPE_SECRET_KEY` raises immediately at startup
with a message naming the setting, rather than failing later on a customer's
first subscribe.

**The test suite is pinned to `mock`** in `config/settings/test.py`, so a
developer with live keys in `.env` cannot have the suite create real Stripe
objects on every run.

---

## 2. Going live

1. Replace the two keys with `sk_live_…` / `pk_live_…`.
2. Point the Dashboard webhook at `https://<host>/webhooks/stripe/billing/`
   and copy its signing secret into `STRIPE_BILLING_WEBHOOK_SECRET`.
3. Redeploy.

That is all. In particular:

**No products or prices need creating by hand.** They are created from Swayp's
own `Plan` table on first use, keyed on plan code and amount, and the resulting
id is cached on the row. The BRD §6.2 numbers stay the single source of truth,
and a dashboard typo cannot silently disagree with the pricing page.

**No data migration.** Existing subscriptions have blank provider ids, which
simply means nothing is being collected for them yet.

---

## 3. The subscribe flow

The card never touches Swayp's servers.

```
1. POST /api/v1/billing/payment-method/setup/
      → { client_secret, publishable_key, collects_money }

2. Client mounts Stripe Elements with publishable_key
   and confirms the SetupIntent with client_secret
      → payment_method_id

3. POST /api/v1/billing/subscription/
      { "plan": "FOUNDING", "payment_method_id": "pm_..." }
      → 201 { ..., "client_secret": "pi_..._secret" }

4. If client_secret is non-empty, confirm it with Stripe.js
   (this is the 3-D Secure step)

5. Stripe calls /webhooks/stripe/billing/ with invoice.paid
      → subscription confirmed ACTIVE
```

**Step 1 returns `collects_money: false` when the provider is `mock`.** That is
not an error — it is the signal that there is nothing to collect, and the
client should skip the card form entirely rather than mount one that can never
work.

**Step 4 is not optional.** Subscriptions are created with
`payment_behavior: default_incomplete`, so the first invoice waits for
confirmation. A client that ignores `client_secret` leaves the subscription at
Stripe status `incomplete` and the card is never charged.

### A declined card

**400**, with a field error and a message safe to display:

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "payment_method_id": "Your card was declined." } }
```

Deliberately **not 402** — the client renders 402 as "upgrade your plan", which
is actively misleading when the plan is fine and the card is not.

### Provider unreachable

**503**, "Your card has not been charged — please try again." Nothing in Swayp
is broken and the customer should retry, which is a different instruction from
"contact support".

---

## 4. Status mapping

Swayp keeps its own status and records Stripe's verbatim in `provider_status`,
so a disagreement is visible rather than lost in translation.

| Stripe | Swayp | Why |
|---|---|---|
| `active`, `trialing` | `ACTIVE` | |
| `incomplete` | `ACTIVE` | The customer chose a plan and Swayp granted the entitlement. Revoking it while a 3-D Secure prompt is on screen punishes them for their bank's security step. A real failure arrives later as `past_due`. |
| `past_due`, `unpaid` | `PAST_DUE` | A failed charge is a fixable card problem. Cutting off a paying business the first time a card expires is the wrong end of the trade. |
| `canceled`, `incomplete_expired` | `CANCELLED` | |
| anything else | unchanged | An unrecognised state never moves the subscription. |

**A cancelled subscription is never resurrected.** Webhook delivery is
out-of-order, and cancellation is a decision rather than an observation, so a
late `invoice.paid` updates `provider_status` and leaves the status alone.

---

## 5. Webhooks

```
POST /webhooks/stripe/billing/
```

Separate from the payment-rail webhooks under `/webhooks/{moov,stripe,lob}/`
for two reasons: Stripe Billing signs with its own scheme
(`Stripe-Signature: t=…,v1=…`, with the timestamp inside the signed payload)
rather than the shared HMAC the rails use, and it concerns subscriptions rather
than money movement.

Verification is delegated to the Stripe SDK, which enforces the timestamp
tolerance that stops a captured payload being replayed days later.

| Event | Effect |
|---|---|
| `invoice.paid`, `invoice.payment_succeeded` | → `ACTIVE` |
| `invoice.payment_failed` | → `PAST_DUE` |
| `customer.subscription.deleted` | → `CANCELLED` |
| `customer.subscription.updated` | mapped from its status |
| anything else | **200, ignored** |

Unrelated events are acknowledged rather than refused. A 400 would have Stripe
retry until it disables the endpoint — taking the events that matter with it.

Local testing:

```bash
stripe listen --forward-to localhost:8000/webhooks/stripe/billing/
```

---

## 6. Per-transaction fees

Same-day ACH, expedited check and check overage accrue in Swayp's `FeeCharge`
ledger and are pushed to the customer's **next invoice** as Stripe invoice
items, rather than charged one at a time. Cheaper in processor fees, and it
matches what `GET /billing/invoice/` already shows.

Recording a fee with the provider is idempotent per fee and **its failure is
swallowed**. The ledger row is the record of truth — it is what the invoice
preview reads and what "100% of missed guarantees refunded" is measured from —
so a Stripe hiccup must never break the payment that generated it.

---

## 7. What is idempotent, and why it matters

| Operation | Guard |
|---|---|
| Customer creation | Searched by `metadata.swayp_account_id` first, plus an idempotency key. A duplicate customer means a customer billed twice. |
| Price creation | Looked up by `lookup_key` derived from plan code and amount. |
| Subscription creation | Keyed on the Swayp subscription id, so a retried request cannot open a second one. |
| Invoice item | Keyed on the fee id. |

Changing a plan's price creates a **new** Stripe price rather than editing the
old one — Stripe prices are immutable, and existing subscribers should not be
silently repriced anyway.

---

## 8. Verified against test mode

The adapter was run against live Stripe test mode, not just mocked. Confirmed
working: customer create + reuse, price create + reuse, SetupIntent,
subscription create with `pm_card_visa`, plan change, invoice item, cancel, and
a declined card via `pm_card_chargeDeclined`.

Two things that only surfaced by doing so:

- **`latest_invoice.payment_intent` no longer exists** on current API versions;
  the client secret is at `latest_invoice.confirmation_secret`. Expanding the
  old path returns nothing silently, which would have left every subscription
  at `incomplete`, never charged, with no error anywhere to explain why. Both
  shapes are read.
- **`payment_methods.attach` returns a new id** when given a shared test token,
  so the attach result — not the id that was sent — must become the default
  payment method.
- **An idempotency key is scoped to its parameters.** Sending email and name
  on the customer create meant an account that renamed itself hit
  `IdempotencyError`, surfacing as a 503 it could never get past. The create
  now carries only the account metadata — byte-identical every time — and the
  details are set by a follow-up update. The obvious fallback, creating
  without a key, was worse: it silently produced the duplicate customer the
  key existed to prevent, and a duplicate customer is an account billed
  twice.

---

## 9. Still open

| Item | Note |
|---|---|
| Proration | `proration_behavior: "none"`, matching Swayp's current policy of no credit on a mid-cycle change. One line in the adapter when the policy is decided. |
| Invoice history | Only the current-cycle preview exists; past Stripe invoices are not surfaced. |
| Dunning | `PAST_DUE` is recorded but no retry or reminder sequence is driven from it. |
