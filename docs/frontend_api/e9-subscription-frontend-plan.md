# E9b — Subscription Frontend Plan

How the web app takes a visitor from **"Get Started"** on the pricing page to a
paid or trialling subscription, and how it handles plan changes, cancellation,
the card on file and plan limits afterwards.

**Every endpoint here is live today.** There is no hosted Stripe Checkout and
no customer portal: the card is collected in the app with **Stripe Elements**,
and Swayp creates the subscription itself.

← [Index](README.md) · Reference with full response bodies: [E9 Billing](e9-billing.md)

---

## 0. Endpoints

| Method | Path | Auth | Used for |
|---|---|---|---|
| GET | `/api/v1/billing/plans` | public | Pricing page, compare table |
| GET | `/api/v1/billing/config` | public | `collects_money`, Stripe publishable key, fee schedule |
| GET | `/api/v1/billing/subscription` | any teammate | Current plan, or `null` |
| POST | `/api/v1/billing/subscription` | owner | Subscribe |
| PATCH | `/api/v1/billing/subscription` | owner | Change plan |
| DELETE | `/api/v1/billing/subscription` | owner | Cancel at period end |
| POST | `/api/v1/billing/subscription/resume` | owner | Undo a pending cancellation |
| GET | `/api/v1/billing/allowances` | any teammate | Usage bars |
| POST | `/api/v1/billing/payment-method/setup` | owner | SetupIntent to add or replace a card |
| GET | `/api/v1/billing/payment-method` | any teammate | Card on file |
| POST | `/api/v1/billing/payment-method` | owner | Replace the card (pays a past-due invoice) |
| GET | `/api/v1/billing/invoice` | any teammate | This cycle's running total |
| GET | `/api/v1/billing/invoices` | any teammate | Past invoices with PDF links |
| GET | `/api/v1/teams/me` | signed in | `capabilities` (is `manage_billing` there?) |

**Owner** means the `manage_billing` capability. Only the account owner has
it; even an Admin doesn't. Everyone else gets **403 `role_forbidden`** on the
owner-only calls.

---

## 1. Routes

| Route | Auth | Purpose |
|---|---|---|
| `/pricing` | public | Plan cards and compare table |
| `/register?plan=CODE` | public | Signup that remembers the selected plan |
| `/login?plan=CODE` | public | Login that remembers the selected plan |
| `/subscribe?plan=CODE` | signed in | Confirm plan, pay if needed, subscribe |
| `/settings/billing` | signed in | Plan, usage, change plan, card, invoices, cancel |

---

## 2. Pricing page (`/pricing`)

```
GET /api/v1/billing/plans      (public; send the token if you have one)
```

Three plans, sorted by price. **Array order is display order.**

| UI element | Field |
|---|---|
| Price `$99 /month` | `monthly_price` (always `/month`; there is no annual price) |
| Description line | `description` |
| "Key Features" list | `features`, in the given order |
| "N founding spots left" badge | `founding_spots_remaining`, when not `null` and > 0 |
| "14-day free trial, no card needed" badge | `trial_eligible === true` **and** `trial_days > 0` |

- **Never hard-code a price.** Render `monthly_price` from this response.
- **Compare table:** build the numeric rows from `seat_limit`,
  `unlimited_seats`, `bank_limit`, `unlimited_banks`, `included_entities` and
  `free_checks_per_month`. `null` limits mean **Unlimited**: test the
  `unlimited_*` flags, never `!limit`. Yes/no rows (1099, approval workflows,
  ERP sync, support) are product copy in one frontend constant keyed by
  `code`.
- **Seats include the owner.** Founding's 3 means the owner plus 2. Write "3
  users", not "3 teammates".
- `trial_eligible` is this account's own answer when a token is sent. Without
  one it is `true`, as for a new account.

### 2.1 Button per plan

| Visitor | Button |
|---|---|
| Signed out | Standard with a trial: "Start Free Trial". Others: "Get Started". → `/register?plan=CODE` |
| Signed in, no subscription, owner | → `/subscribe?plan=CODE` |
| Signed in, on this plan | "Current plan", disabled |
| Signed in, on another plan, owner | "Upgrade" or "Downgrade" → change-plan dialog (§6) |
| Signed in, not owner | Disabled, "Ask your account owner" |

- Rank for upgrade vs downgrade: `FOUNDING < STANDARD < ENTERPRISE`. Keep it
  in one helper, `planRank(code)`.
- `trial_eligible: false`: Standard says "Get Started", not "Start Free Trial".
- Founding with `lock_available: false`: hide the spots badge. Subscribing
  still works, at list price without the lock.

---

## 3. Remembering the selected plan through sign-up and sign-in

The chosen plan has to survive registration, email verification and the
two-step sign-in. The backend doesn't store it, so keep it in the browser.

```ts
// lib/planIntent.ts
const KEY = "swayp.planIntent";
const VALID = ["FOUNDING", "STANDARD", "ENTERPRISE"] as const;
export type PlanCode = typeof VALID[number];

export function savePlanIntent(code: string | null) {
  if (code && (VALID as readonly string[]).includes(code)) {
    try { localStorage.setItem(KEY, code); } catch {}
  }
}
export function readPlanIntent(): PlanCode | null {
  try { return localStorage.getItem(KEY) as PlanCode | null; } catch { return null; }
}
export function clearPlanIntent() {
  try { localStorage.removeItem(KEY); } catch {}
}
```

1. `/register` and `/login` read `?plan=` on mount and call `savePlanIntent`.
2. Keep `?plan=` on every auth link ("Log in instead", "Forgot password").
3. Ignore unknown codes. Never send the raw query string to the API.

`localStorage` rather than `sessionStorage`, so the choice survives the user
opening the verification email in a new tab. If it's lost anyway (another
device), the router in §4 sends them to `/pricing` to pick again.

---

## 4. After sign-in: where to send the user

Run once after every completed sign-in (including the two-step code) and
after email verification:

```ts
async function routeAfterAuth() {
  const plan = readPlanIntent();
  const sub = (await api.get("/billing/subscription")).data; // null when none
  const me = (await api.get("/teams/me")).data;
  const isOwner = me.capabilities.includes("manage_billing");

  if (!sub) {
    if (!isOwner) return go("/no-plan");             // "Your account owner needs to choose a plan"
    return go(plan ? `/subscribe?plan=${plan}` : "/pricing");
  }

  clearPlanIntent();
  if (plan && plan !== sub.plan.code && isOwner) {
    return go(`/settings/billing?change=${plan}`);   // opens the change-plan dialog (§6)
  }
  return go("/dashboard");
}
```

- `GET /billing/subscription` answers **200 with `data: null`** when there is
  no subscription. That's not an error.
- A past-due subscription is still a subscription: go to the dashboard and
  show the past-due banner (§7.2), not to `/subscribe`.

---

## 5. Subscribing (`/subscribe?plan=CODE`)

Show the plan summary (name, `monthly_price`, features) and one confirm
button. What happens on confirm depends on two things:

```
GET /api/v1/billing/config  →  { "collects_money": true, "publishable_key": "pk_test_…", "fees": { … } }
```

| Case | When | Flow |
|---|---|---|
| **A. Free trial** | `collects_money` and the plan's `trial_eligible` and `trial_days > 0` | §5.1, no card |
| **B. Paid** | `collects_money`, no trial | §5.2, card through Stripe |
| **C. Not charging** | `collects_money: false` (the mock deployment) | §5.1, no card ever |

Every subscribe call:

```
POST /api/v1/billing/subscription
Idempotency-Key: <one uuid per click>
{ "plan": "STANDARD" }
```

The `Idempotency-Key` makes a double click or a retry return the same
subscription instead of starting a second one. Make a new key per click, and
reuse it only when retrying that same click.

### 5.1 Trial or not charging: one call

`201`, with `client_secret` empty:

```json
{ "id": "…", "plan": { "code": "STANDARD", "…": "…" }, "status": "ACTIVE",
  "effective_price": "99.00", "locked_price": null,
  "is_trialing": true, "trial_days_remaining": 14, "trial_end": "2026-11-30",
  "provider_status": "trialing", "client_secret": "",
  "past_due": false, "cancel_pending": false, "cancels_on": null }
```

Done: `clearPlanIntent()`, refresh the cached subscription, show "Welcome to
Standard", go to onboarding or the dashboard. The card can be added later
(§7.4); remind the user before `trial_end`.

### 5.2 Paid: subscribe, then pay with Stripe

1. **Subscribe first**, as above, with no card. When money is collected, the
   `201` carries a non-empty **`client_secret`**: the first invoice's payment,
   waiting for a card. `provider_status` is `"incomplete"`.
2. **Mount Stripe's Payment Element with that `client_secret`** and confirm:

```ts
const stripe = await loadStripe(config.publishable_key);
const elements = stripe.elements({ clientSecret: sub.client_secret });
elements.create("payment").mount("#card");

// on "Pay $99":
const { error } = await stripe.confirmPayment({
  elements,
  confirmParams: { return_url: `${location.origin}/subscribe/done` },
  redirect: "if_required",
});
```

   Stripe handles 3-D Secure inside `confirmPayment`. The card goes to Stripe
   only and never to Swayp.
3. **On success,** refetch `GET /billing/subscription` until `provider_status`
   is `"active"` (every 1.5 s, up to about 20 s; it is updated by Stripe's
   webhook). Then clear the plan intent and continue as in §5.1. If it's still
   `"incomplete"` after 20 s, say "We're confirming your payment" with a
   Refresh button. **Don't subscribe again.**
4. **On `error`** (declined, 3-D Secure failed): show `error.message` and let
   the user try another card **in the same Payment Element**. Don't call
   subscribe again; the subscription already exists.

**Keep the `client_secret` for this page only.** It is returned once and
can't be fetched again. Don't store it.

⚠️ **Known gap: an abandoned first payment.** If the user leaves or reloads
before paying, the app has no way to get the `client_secret` back, and a
second subscribe answers `400 already_subscribed`. The subscription shows as
`status: "ACTIVE"` with `provider_status: "incomplete"`. Stripe expires it
after about 23 hours, it then becomes `CANCELLED`, and the user can subscribe
again. Until the backend adds a retry, show "Your payment wasn't completed.
Please try again tomorrow or contact support" when `GET /billing/subscription`
returns `provider_status: "incomplete"` on a later visit. **Don't** treat
`status: "ACTIVE"` alone as paid on the billing screen.

### 5.3 Errors

| Response | Meaning | Show |
|---|---|---|
| 400 `already_subscribed` | the account has a plan already | go to `/settings/billing` |
| 400 `card_declined` on `errors.payment_method_id` | only when a card was sent | "Your card was declined." |
| 403 `role_forbidden` | not the owner | "Only the account owner can choose a plan" |
| 503 | billing provider unreachable | "Billing is temporarily unavailable. You have not been charged." with Retry |

---

## 6. Changing plan

Entry points: a pricing card while signed in, "Change plan" on
`/settings/billing`, the upgrade dialog from a 402 (§8), and `?change=CODE`.

```
PATCH /api/v1/billing/subscription      { "plan": "ENTERPRISE" }
```

**How it works today:**

- **It applies immediately**, upgrade or downgrade. The new limits apply at
  once.
- **The cycle dates stay the same and there is no proration**: no partial
  charge now and no credit. The next invoice is at the new plan's price.
- **There is no preview endpoint.** Build the confirm dialog from
  `GET /billing/plans` and the current subscription:

| Case | Dialog copy |
|---|---|
| Upgrade | "Switch to Enterprise now. From your next bill on {period_end} you'll pay $299/month. Nothing is charged today." |
| Downgrade | "Switch to Founding now. Your limits change immediately, and from {period_end} you'll pay $X/month. No refund for this month." |
| Leaving Founding with `locked_price !== null` | ⚠️ "You'll lose your Founding rate of ${locked_price} permanently." Require a checkbox. |
| During a trial | "Your trial continues. Billing starts on {trial_end} at $X/month." |

**Check that the account fits before offering a downgrade.** Compare
`GET /billing/allowances` (`SEATS.used`, `BANKS.used`) against the target
plan's `seat_limit` and `bank_limit` from `/plans` (skip when `unlimited_*`).
Pending invitations count as seats. If it doesn't fit, list what is over and
disable the button. The backend checks again anyway:

| Response | Do |
|---|---|
| 200 | Refresh the subscription and allowances; show a toast |
| 402 `plan_limit` | Too small for the account's usage. Show `message` verbatim; it names what is over. |
| 400 | No subscription to change → `/subscribe` |
| 403 `role_forbidden` | Not the owner |

---

## 7. `/settings/billing`

Data: `GET /billing/subscription`, `/billing/allowances`,
`/billing/payment-method`, `/billing/invoice`, `/billing/invoices`, and
`/teams/me` for `manage_billing`.

### 7.1 Current plan card

| Show | From |
|---|---|
| Plan name | `plan.name` |
| Price | **`effective_price`**, never `plan.monthly_price` (a locked Founding price wins) |
| "Founding rate locked" chip | `locked_price !== null` |
| Next bill | `period_end`, or `trial_end` while `is_trialing` |
| Usage bars | `GET /billing/allowances`. "Resets on {period_end}" only on **CHECKS**. |

Allowances: branch on `unlimited`, not on `limit`. `CHECKS` never blocks
(each extra check costs $2.99, from `config.fees.check_overage`). `SEATS` and
`BANKS` answer 402 at the limit.

### 7.2 Banner (show one, in this order)

| Condition | Banner | Action |
|---|---|---|
| `past_due` | "Your last payment failed. Update your card to keep your plan." | "Update card" (§7.4) |
| `provider_status === "incomplete"` | "Your first payment wasn't completed." (see §5.2 gap) | Contact support |
| `cancel_pending` | "Your plan ends on {cancels_on}." | "Keep my plan" → §7.3 |
| `is_trialing` | "{trial_days_remaining} days left in your free trial." When ≤ 3 and no card: "Add a card to continue after {trial_end}." | "Add card" (§7.4) |

`trial_days_remaining` is `0` when the trial has run out and `null` when there
was never one. Treat them differently.

### 7.3 Cancel and resume

```
DELETE /api/v1/billing/subscription
POST   /api/v1/billing/subscription/resume
```

- **Cancel keeps the paid period.** The plan stays fully active until
  `cancels_on` (the end of the paid month, or the trial's end), then ends.
  Nothing is refunded. Confirm first: "You'll keep access until {date}."
- **Resume** withdraws a pending cancellation. 400 when none is pending.
- While a cancellation is pending, subscribing to another plan is refused;
  use change plan (§6) instead.

### 7.4 Card on file

```
GET  /api/v1/billing/payment-method
→ { "brand": "visa", "last4": "4242", "exp_month": 12, "exp_year": 2030 }   or null
```

To **add or replace** the card (needs a subscription first):

1. `POST /api/v1/billing/payment-method/setup` → `{ client_secret: "seti_…", publishable_key, collects_money }`.
   Call it only when opening the card form; every call creates a SetupIntent.
2. Mount the Payment Element with that `client_secret` and call
   `stripe.confirmSetup({ elements, redirect: "if_required" })`.
3. `POST /api/v1/billing/payment-method { "payment_method_id": setupIntent.payment_method }`.

The new card becomes the default. **If the subscription is past due, the
unpaid invoice is charged to it at once** and the subscription returns to
`ACTIVE`. A decline is 400 on `errors.payment_method_id`.

With `collects_money: false`, `setup` returns `collects_money: false` and an
empty `client_secret`: hide all card controls.

### 7.5 Invoices

- `GET /api/v1/billing/invoice`: this cycle's running total (plan, add-ons,
  fees). Render `total`, not unit prices.
- `GET /api/v1/billing/invoices`: past invoices, newest first, each with
  `pdf_url`. Paged by cursor: send `next_cursor` back as `starting_after`;
  `null` means the last page. Empty when nothing collects money.

### 7.6 Not the owner

Show the plan, usage and invoices read-only. Hide Change, Cancel and card
buttons, and show "Managed by the account owner."

---

## 8. Plan limits: the global 402 handler

Put this in the one fetch wrapper. **402 = a bigger plan fixes it. 403 = the
role forbids it. Never treat them alike.**

```ts
if (res.status === 402 && body.code === "plan_limit") {
  // body.limit: "SEATS" | "BANKS"
  return openUpgradeDialog({
    message: body.message,                         // show verbatim
    suggested: cheapestPlanThatLifts(body.limit),  // from GET /billing/plans
  });
}
```

- `cheapestPlanThatLifts("BANKS")`: the first plan by rank with
  `unlimited_banks` or a higher `bank_limit`. Same for `SEATS`.
- The dialog's button opens the change-plan dialog (§6), or `/subscribe` when
  there is no subscription. For a non-owner it says "Ask your account owner
  to upgrade".
- When the account is past due, show the past-due banner instead of an
  upgrade prompt.

**Avoid the 402 up front:** before opening Plaid, check
`allowances.BANKS.remaining`; before inviting, check `SEATS.remaining`. If
it's 0, show the upgrade prompt instead.

Keep plan state in **one** shared store (`useSubscription()` caching
`/billing/subscription` and `/billing/allowances`). Invalidate it after
subscribing, changing plan, cancel or resume, a card change, a bank link or
unlink, and an invite or removal.

---

## 9. Edge cases

- [ ] Double click on Subscribe: disable the button while waiting; the
      `Idempotency-Key` makes a retry safe.
- [ ] Two tabs subscribe at once: the second gets `400 already_subscribed` →
      go to billing settings.
- [ ] Card declined in the Payment Element: retry in the same element, never
      call subscribe again.
- [ ] Payment succeeded but `provider_status` is still `incomplete`: wait and
      refetch, don't resubscribe.
- [ ] Founding spots run out between the pricing page and subscribing: show
      `effective_price` from the response ("Your price: $X/month") and don't
      promise the lock.
- [ ] Trial already used: Standard shows "Get Started" and goes through the
      paid flow (§5.2).
- [ ] Teammate without `manage_billing`: never sees subscribe, change, cancel
      or card buttons.
- [ ] `collects_money: false`: the whole flow works with no card screens.
- [ ] Back button onto `/subscribe` after subscribing: check
      `GET /billing/subscription` on mount and redirect to billing settings
      if one exists.

---

## 10. Build order

| Step | Scope |
|---|---|
| 1 | Pricing page from `GET /plans`, buttons, `planIntent` helpers, `?plan=` on register and login |
| 2 | Post-sign-in router, `useSubscription()` store, global 402 handler |
| 3 | `/subscribe`: trial and not-charging flow (§5.1) |
| 4 | `/subscribe`: paid flow with the Payment Element (§5.2) |
| 5 | Billing settings: plan card, usage, banners, cancel and resume, invoices |
| 6 | Card on file: add or replace (§7.4) |
| 7 | Change-plan dialog with the fit check (§6) |

---

## 11. QA with Stripe test mode

| Scenario | Card | Expect |
|---|---|---|
| Standard, first time | none | `is_trialing: true`, `trial_days_remaining: 14`, no card screen |
| Founding, paid | `4242 4242 4242 4242` | `provider_status` becomes `active`; `locked_price` set while spots remain |
| 3-D Secure | `4000 0025 0000 3155` | Stripe shows the challenge inside `confirmPayment`, then success |
| Declined | `4000 0000 0000 0002` | Error in the Payment Element; retry in place; no second subscription |
| Downgrade that doesn't fit | Standard → Founding with 2 banks | Button disabled; forcing it returns 402 `plan_limit` |
| Cancel, then resume | — | `cancel_pending` true with `cancels_on`, then false |
| Past due | update to `4000 0000 0000 0341`, let a renewal fail | `past_due` banner; replacing the card returns it to `ACTIVE` |
| Not charging | mock deployment | No card screens anywhere; subscribe is one call |
