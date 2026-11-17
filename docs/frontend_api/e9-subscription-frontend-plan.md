# E9b — Subscription Frontend Plan

How the web app takes a visitor from **"Get Started"** on the pricing page to a
paid or trialling subscription, and how it handles plan changes, cancellation,
the card on file and plan limits afterwards.

**The app never shows a card form.** Every payment happens on a page Stripe
hosts: **Stripe Checkout** for the first payment, the **Customer Portal** for
the card, invoices and cancel, and the **hosted invoice page** when a plan
switch ends a trial. A trial starts with no Stripe page at all.

The older in-app card flow (SetupIntent, Payment Element, `client_secret`)
still works and is kept for mobile; the web app should not use it.

← [Index](README.md) · Reference with full response bodies: [E9 Billing](e9-billing.md)

---

## 0. Endpoints

| Method | Path | Auth | Used for |
|---|---|---|---|
| GET | `/api/v1/billing/plans` | public | Pricing page, compare table |
| GET | `/api/v1/billing/config` | public | `collects_money`, Stripe publishable key, fee schedule |
| GET | `/api/v1/billing/subscription` | any teammate | Current plan, or `null` |
| POST | `/api/v1/billing/checkout-session` | owner | **Start a plan** (every plan button): starts a trial, or returns the Stripe Checkout URL |
| GET | `/api/v1/billing/checkout-session/{session_id}` | owner | Success page polls until `complete` |
| POST | `/api/v1/billing/portal-session` | owner | Stripe Customer Portal URL: card, invoices, cancel |
| POST | `/api/v1/billing/subscription` | owner | Subscribe in-app (mobile; not for web) |
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

## 5. Starting a plan (`/subscribe?plan=CODE`)

Show the plan summary (name, `monthly_price`, features) and one button. The
label follows the plan ("Start Free Trial" when `trial_eligible` and
`trial_days > 0`, otherwise "Get Started"), but **the backend decides what
happens**, not the label: a returning account gets no second trial, whatever
the button said. Every plan uses the same call:

```
POST /api/v1/billing/checkout-session
Idempotency-Key: <one uuid per click>
{ "plan": "FOUNDING" }
```

Follow `action` in the answer:

| `action` | Status | When | Do |
|---|---|---|---|
| `subscribed` | 201 | A trial applies | `subscription` is set and `url` is null. No payment, no card. Clear the plan intent, refresh the subscription, go to onboarding or the dashboard. |
| `redirect` | 200 | Anything to pay now (Founding, Enterprise, Standard without a trial) | `window.location.href = url` (Stripe's page). Nothing is created in Swayp yet. |

```json
{ "action": "redirect",
  "url": "https://checkout.stripe.com/c/pay/cs_test_…",
  "session_id": "cs_test_…",
  "subscription": null }
```

A second click while a page is still open returns **the same** page, so a
user cannot pay twice.

### 5.1 Coming back from Stripe

- **Paid:** Stripe sends the browser to
  `/billing/success?session_id=cs_test_…`. That page polls
  `GET /api/v1/billing/checkout-session/{session_id}` every 2 s until
  `status` is `complete` (usually the first or second call), then clears the
  plan intent, refreshes the subscription and goes to onboarding or the
  dashboard. After about 30 s, show "We're confirming your payment" with a
  Refresh button. **Never start checkout again from this page.**

  ```json
  { "session_id": "cs_test_…", "status": "complete", "plan": "FOUNDING",
    "subscription": { "plan": { "code": "FOUNDING" }, "status": "ACTIVE", "locked_price": "29.00", "…": "…" } }
  ```

  `status: "expired"` means the page timed out unpaid: send the user to
  `/pricing?plan=CODE`.
- **Backed out:** Stripe sends the browser to `/pricing?plan=CODE`. Nothing
  was created; the account still has no plan, and the paywall (§8) keeps
  sending it to pricing.

**The Founding rate is claimed when the payment completes**, not when the
page opens. Near the last spot, a user who opened the page may pay list
price: the success page shows `locked_price` (null means no founder rate).

**Locally** (`collects_money: false`), `url` points straight at
`/billing/success?session_id=…` and the session is already `complete`, so
the whole round trip works without Stripe.

### 5.2 Errors

| Response | Meaning | Show |
|---|---|---|
| 400 `already_subscribed` | the account has a plan already | go to `/settings/billing` |
| 403 `role_forbidden` | not the owner | "Only the account owner can choose a plan" |
| 404 on the status poll | not this account's checkout | go to `/pricing` |
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
- **Exception: during a trial, a move to a plan with no trial (Founding) ends
  the trial and charges the new price today**, starting a new cycle. If the
  response has a non-empty **`payment_url`**, no card was on file: send the
  browser to it (Stripe's hosted invoice page). Until it is paid,
  `past_due` is true and the past-due banner shows.
  Dialog copy: "Founding has no free trial. Switching ends your trial and
  charges $29 today." The switch also claims the Founding rate
  (`locked_price`) while spots remain.
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
| `past_due` | "Your last payment failed. Update your card to keep your plan." | "Update card" → portal (§7.4) |
| `cancel_pending` | "Your plan ends on {cancels_on}." | "Keep my plan" → §7.3 |
| `is_trialing` | "{trial_days_remaining} days left in your free trial." When ≤ 3 and no card: "Add a card to continue after {trial_end}." | "Add card" → portal (§7.4) |

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

To **add or replace** the card, or **pay an unpaid invoice**, open the
Stripe Customer Portal:

```ts
const { url } = (await api.post("/billing/portal-session")).data;
window.location.href = url;   // Stripe returns the user to /settings/billing
```

The portal also lists invoices and lets the owner cancel at period end. It
does **not** change plans; that stays in the app (§6). On return, refetch
the subscription: Stripe's webhook updates `past_due`, `cancels_on` and the
card. Locally (`collects_money: false`) `url` is just `/settings/billing`.

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
if (res.status === 402 && body.code === "subscription_required") {
  // No live plan (never subscribed, backed out of Stripe, or cancelled).
  return isOwner ? go("/pricing") : go("/no-plan");
}
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

**The paywall.** With no live subscription, every product endpoint (bills,
vendors, payments, banks, team, reports, dashboard) answers
`402 subscription_required`, `limit: null`. Billing, profile, onboarding and
`GET /teams/me` stay open so the user can choose a plan. A trial and a
past-due plan both keep access; a cancelled plan loses it once it ends.

**Avoid the 402 up front:** before opening Plaid, check
`allowances.BANKS.remaining`; before inviting, check `SEATS.remaining`. If
it's 0, show the upgrade prompt instead.

Keep plan state in **one** shared store (`useSubscription()` caching
`/billing/subscription` and `/billing/allowances`). Invalidate it after
subscribing, changing plan, cancel or resume, a card change, a bank link or
unlink, and an invite or removal.

---

## 9. Edge cases

- [ ] Double click on the plan button: disable it while waiting; the
      `Idempotency-Key` and the reused open session make a retry safe.
- [ ] Two tabs pay two Checkout pages: only one subscription is created.
      The other tab's success page still lands on the one plan.
- [ ] Card declined on Stripe's page: Stripe handles the retry; the app
      sees nothing until the payment succeeds.
- [ ] Success page loads before the webhook: the status poll asks Stripe
      directly; keep polling, never restart checkout.
- [ ] Backed out of Stripe: back on `/pricing`, still no plan; the paywall
      402 keeps the user there.
- [ ] Founding spots run out while the page is open: the success page shows
      `locked_price: null`; don't promise the founder rate.
- [ ] Trial already used: the button may say "Start Free Trial", but the
      answer is `redirect`; just follow it.
- [ ] Teammate without `manage_billing`: never sees plan, change, cancel or
      card buttons; on the paywall 402 show `/no-plan`.
- [ ] `collects_money: false`: the round trip works with no Stripe pages.
- [ ] Back button onto Stripe's page after paying: Stripe shows it as
      complete; the success page handles a repeat visit.

---

## 10. Build order

| Step | Scope |
|---|---|
| 1 | Pricing page from `GET /plans`, buttons, `planIntent` helpers, `?plan=` on register and login |
| 2 | Post-sign-in router, `useSubscription()` store, global 402 handler |
| 3 | `/subscribe`: `POST checkout-session`, follow `action` (§5) |
| 4 | `/billing/success`: the status poll (§5.1) |
| 5 | Billing settings: plan card, usage, banners, cancel and resume, invoices |
| 6 | "Manage card / invoices" → Customer Portal (§7.4) |
| 7 | Change-plan dialog with the fit check (§6) |

---

## 11. QA with Stripe test mode

| Scenario | Card | Expect |
|---|---|---|
| Standard, first time | none | `is_trialing: true`, `trial_days_remaining: 14`, no card screen |
| Founding, paid | `4242 4242 4242 4242` on Stripe's page | Back on `/billing/success`, `status: complete`; `locked_price` set while spots remain |
| 3-D Secure | `4000 0025 0000 3155` | Stripe shows the challenge on its page, then success |
| Declined | `4000 0000 0000 0002` | Stripe shows the error and lets the user retry; nothing created in Swayp |
| Backed out | — | Back on `/pricing`; product pages answer 402 `subscription_required` |
| Trial → Founding, no card | — | `PATCH` returns `payment_url`; paying it clears `past_due` |
| Downgrade that doesn't fit | Standard → Founding with 2 banks | Button disabled; forcing it returns 402 `plan_limit` |
| Cancel, then resume | — | `cancel_pending` true with `cancels_on`, then false |
| Past due | update to `4000 0000 0000 0341` in the portal, let a renewal fail | `past_due` banner; a new card in the portal returns it to `ACTIVE` |
| Not charging | mock deployment | No Stripe pages anywhere; the round trip completes at once |
