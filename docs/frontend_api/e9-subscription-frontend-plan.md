# E9b — Subscription Frontend Plan (Checkout, Plan Changes, Gates)

How the web app takes a visitor from **"Get Started"** on the pricing page to a
paid (or trialling) subscription, and how it handles upgrade, downgrade,
proration, feature limits and cancellation afterwards.

← [Index](README.md) · Reference: [E9 Billing](e9-billing.md) ·
Backend plan: [Stripe subscription plan](../stripe-subscription-plan.md)

Status: **plan** · Date: 2026-11-14

---

## 0. Legend: what you can build now

| Mark | Meaning |
|---|---|
| ✅ | Endpoint is live today. Build against it. |
| 🔜 | Planned in the [backend plan](../stripe-subscription-plan.md). The shape here is the agreed contract, so build behind a feature flag, or mock it. |

| Method | Path | Status | Used by |
|---|---|---|---|
| GET | `/api/v1/billing/plans` | ✅ | Pricing page, compare table |
| GET | `/api/v1/billing/config` | ✅ | `collects_money` (mock vs Stripe) |
| GET | `/api/v1/billing/subscription` | ✅ | Post-auth router, billing screen |
| PATCH | `/api/v1/billing/subscription` | ✅ (behaviour changes 🔜) | Change plan |
| GET | `/api/v1/billing/allowances` | ✅ | Usage bars, downgrade warnings |
| GET | `/api/v1/billing/invoices` | ✅ | Billing history |
| POST | `/api/v1/billing/checkout-session` | 🔜 | Redirect to Stripe Checkout |
| GET | `/api/v1/billing/checkout-session/{id}` | 🔜 | Success page polling |
| GET | `/api/v1/billing/subscription/change-preview?plan=` | 🔜 | Proration preview modal |
| DELETE | `/api/v1/billing/subscription/scheduled-change` | 🔜 | Undo a pending downgrade |
| POST | `/api/v1/billing/portal-session` | 🔜 | Cancel, card, invoices (Stripe portal) |
| POST | `/api/v1/auth/register` + `plan` | 🔜 (optional field) | Remember the chosen plan |

**Open product decisions** (see backend plan §0). They affect copy only, not structure:

- **Founding price**: the design shows $29, but the backend and BRD say $49. **Always render `monthly_price` from `GET /plans`; never hard-code it.** Then whichever value is decided appears automatically.
- **Enterprise "Get Started"**: self-serve checkout, or "Contact sales". Build it as a checkout, and keep a flag (`ENTERPRISE_SELF_SERVE`) so it can switch to a sales link.

---

## 1. Routes

| Route | Auth | Purpose |
|---|---|---|
| `/pricing` | public | Plan cards and compare table |
| `/register?plan=CODE` | public | Signup that carries the selected plan |
| `/login?plan=CODE` | public | Login that carries the selected plan |
| `/checkout?plan=CODE` | signed in | Thin page: calls `checkout-session`, then redirects |
| `/billing/success?session_id=cs_…` | signed in | Stripe `success_url`; waits for fulfilment |
| `/pricing?plan=CODE&checkout=cancelled` | public | Stripe `cancel_url`; shows "No charge was made" |
| `/settings/billing` | signed in | Current plan, usage, change plan, invoices, cancel |

---

## 2. Pricing page (`/pricing`)

### 2.1 Data

```
GET /api/v1/billing/plans        (public; send the token if you have one)
```

Use these fields per plan:

| UI element | Field |
|---|---|
| Price `$99 /month` | `monthly_price`, `billing_interval` |
| Description line | `description` |
| "Key Features" list | `features`, in the given order |
| "497 founding spots left" badge | `founding_spots_remaining` (only when not null and > 0) |
| "14-day free trial, no card needed" badge | `trial_eligible === true` **and** `trial_days > 0` |
| CTA label | See §2.2 |

**Compare table.** Build the numeric rows (team members, banks, entities, mailed checks) from `seat_limit`, `unlimited_seats`, `bank_limit`, `unlimited_banks`, `included_entities` and `free_checks_per_month`. The yes/no rows (1099, approval workflows, ERP sync, support tier) are product copy kept in one frontend constant keyed by `code`, until the backend exposes them (🔜 `support_tier`).

`null` limits mean **Unlimited**. Test the `unlimited_*` flags, never `!limit`.

### 2.2 CTA per plan, by visitor state

| Visitor state | Founding | Standard | Enterprise |
|---|---|---|---|
| Signed out | "Get Started" → `/register?plan=FOUNDING` | "Start Free Trial" → `/register?plan=STANDARD` | "Get Started" → `/register?plan=ENTERPRISE` |
| Signed in, no subscription | → `/checkout?plan=…` | → `/checkout?plan=…` | → `/checkout?plan=…` |
| Signed in, **on this plan** | "Current plan" (disabled) | same | same |
| Signed in, on another plan | "Upgrade" or "Downgrade" → change-plan modal (§6) | same | same |
| Signed in, not owner (no `manage_billing`) | "Ask your account owner" (disabled, tooltip) | same | same |

- If the user has no trial left (`trial_eligible: false`), Standard says **"Get Started"**, not "Start Free Trial".
- If Founding spots are gone (`lock_available: false`), hide the spots badge and show **"Founding rate closed"**. Keep the card only if product wants to still sell it at list price.
- Upgrade vs downgrade order: `FOUNDING < STANDARD < ENTERPRISE`. Put it in one shared helper: `planRank(code)`.

---

## 3. Carrying the selected plan through auth

The plan must survive registration, email verification and two-step sign-in, including when the user verifies on another device.

```ts
// lib/planIntent.ts
const KEY = "swayp.planIntent";
const VALID = ["FOUNDING", "STANDARD", "ENTERPRISE"] as const;
type PlanCode = typeof VALID[number];

export function savePlanIntent(code: string | null) {
  if (code && VALID.includes(code as PlanCode)) {
    try { sessionStorage.setItem(KEY, code); } catch {}
  }
}
export function readPlanIntent(): PlanCode | null {
  try { return sessionStorage.getItem(KEY) as PlanCode | null; } catch { return null; }
}
export function clearPlanIntent() {
  try { sessionStorage.removeItem(KEY); } catch {}
}
```

1. `/register` and `/login` read `?plan=` on mount and call `savePlanIntent`.
2. Keep `?plan=` on every auth link: "Already have an account? Log in", "Forgot password", and the 2FA step.
3. 🔜 Send `plan` in the `POST /auth/register` body. The backend stores it as `intended_plan`, so it is restored after email verification on another device. It shows up on `GET /users/me/profile` as `intended_plan` (🔜).
4. **Validate it.** Ignore unknown codes. Never pass a raw query string to the API.

---

## 4. After auth: the post-auth router

Run this once after every successful sign-in (including a completed 2FA step) and after email verification:

```ts
async function routeAfterAuth() {
  const plan = readPlanIntent() ?? profile.intended_plan ?? null;
  const sub = (await api.get("/billing/subscription")).data; // null when none

  if (!sub) {
    return plan ? go(`/checkout?plan=${plan}`) : go("/pricing");
  }
  clearPlanIntent();
  if (plan && plan !== sub.plan.code) {
    return go(`/settings/billing?change=${plan}`); // opens change-plan modal (§6)
  }
  return go("/dashboard");
}
```

- `GET /billing/subscription` answers **`data: null`** (200) when there is no subscription. That's not an error.
- `PAST_DUE` is still a subscription. Send the user to the dashboard and show the past-due banner (§7.3). Don't send them to checkout.
- A user without `manage_billing` (a teammate) with no subscription goes to a "Your account owner needs to choose a plan" screen, not to checkout. The checkout call would answer 403.

---

## 5. Checkout

### 5.1 `/checkout?plan=CODE`

A short loading page ("Taking you to secure checkout…"):

```
POST /api/v1/billing/checkout-session      🔜
{ "plan": "STANDARD" }
Idempotency-Key: <uuid per click>
```

```json
{ "success": true, "data": { "url": "https://checkout.stripe.com/c/pay/cs_…", "session_id": "cs_…" } }
```

Then `window.location.assign(data.url)`. Use a full navigation, not `fetch`, and not an iframe.

| Response | Do |
|---|---|
| 200 | Redirect to `url` |
| 400 `already_subscribed` | Go to `/settings/billing` (they already have a plan) |
| 403 `role_forbidden` | "Only the account owner can choose a plan" |
| 503 | "Billing is temporarily unavailable. You have not been charged." Show a Retry button. |

**Mock mode** (`GET /billing/config` → `collects_money: false`): the backend returns a `url` pointing straight to `/billing/success?session_id=mock_…`. Use the same code path; nothing changes on the frontend.

**Standard trial**: Stripe Checkout skips card entry by itself when the trial needs no card. Don't build a separate "Start trial" call.

### 5.2 `/billing/success?session_id=…`

Stripe redirects here **before** our webhook may have run. Poll:

```
GET /api/v1/billing/checkout-session/{session_id}     🔜
→ { "status": "open" | "complete" | "expired", "subscription": { … } | null }
```

- Poll every 1.5 s, up to about 20 s. Stop as soon as `status === "complete"` **and** `subscription` is not null.
- On success: `clearPlanIntent()`, refresh the cached subscription, show "Welcome to Standard", then go to `/dashboard` (or onboarding if it isn't finished).
- If the timeout passes while still `open`: "We're confirming your payment. This can take a minute." Show a Refresh button. **Don't** send the user back to checkout, because they may already have paid.
- `expired`: go to `/pricing?plan=…` with "Your checkout session expired. No charge was made."
- Never decide that the payment succeeded from the URL alone. Only the API response decides.

### 5.3 Cancelled checkout

`/pricing?plan=CODE&checkout=cancelled`: show a dismissible note, "Checkout cancelled. You have not been charged." Keep the plan intent so one click restarts checkout.

---

## 6. Changing plan: upgrade, downgrade, proration

Entry points: a pricing card while signed in, "Change plan" on `/settings/billing`, the upgrade prompt from a 402 (§8), and `?change=CODE`.

### 6.1 Preview first, always

```
GET /api/v1/billing/subscription/change-preview?plan=ENTERPRISE      🔜
```

```json
{
  "direction": "upgrade",
  "effective": "now",
  "amount_due_now": "133.33",
  "next_invoice_total": "299.00",
  "next_invoice_date": "2026-12-01",
  "fits": true,
  "over": [],
  "removes_addons": [],
  "loses_price_lock": false
}
```

Show a confirmation modal:

| Case | Modal copy | Confirm button |
|---|---|---|
| **Upgrade** (`effective: "now"`) | "You'll be charged **$133.33** today for the rest of this billing period. From Dec 1 you'll pay $299/month." | "Upgrade and pay $133.33" |
| **Upgrade during trial** (`amount_due_now: "0.00"`) | "No charge now. Your trial continues, and billing starts on {trial_end} at $X/month." | "Switch plan" |
| **Downgrade** (`effective: "2026-12-01"`) | "You'll keep Enterprise until **Dec 1**, then move to Standard at $99/month. No refund for the current period." | "Schedule downgrade" |
| **Doesn't fit** (`fits: false`) | List each `over` row: "3 connected banks in use, Founding allows 1". Link to where they can be removed (Banking, Team, Entities). | Disabled |
| `removes_addons` not empty | "These Enterprise add-ons will end: Approval workflows, ERP sync." | Same as the base case |
| `loses_price_lock: true` | ⚠️ "You'll lose your Founding rate of $X permanently." | Needs a checkbox |

**Show the amounts exactly as the API returns them. Never compute proration on the client.**

### 6.2 Apply

```
PATCH /api/v1/billing/subscription      ✅ (proration behaviour 🔜)
{ "plan": "ENTERPRISE" }
```

| Response | Do |
|---|---|
| 200, `plan.code` = new plan | Upgrade done. Refresh the subscription and allowances, then show a toast. |
| 200, `scheduled_change: { plan, effective_on }` 🔜 | Downgrade scheduled. Show the banner from §7.2. |
| 200 with `client_secret` | 3-D Secure is required for the proration charge. Confirm with Stripe.js `confirmCardPayment(client_secret)`, then refetch. |
| 400 `card_declined` | "Your card was declined." Open the portal (§7.4) so they can update it. The plan has **not** changed. |
| 402 `plan_limit` | Usage changed since the preview. Re-open the preview modal. |

### 6.3 Undo a scheduled downgrade

```
DELETE /api/v1/billing/subscription/scheduled-change      🔜
```

### 6.4 Rules the UI must show

- While a downgrade is pending, the **lower** limits already apply to new additions. The backend returns 402 for them. Explain this in the banner: "New banks and members are limited to Standard's allowance until then."
- Plan changes happen **in our app**, never in the Stripe portal. The portal can't check whether the account fits the smaller plan.

---

## 7. `/settings/billing`

Data: `GET /billing/subscription`, `GET /billing/allowances`, `GET /billing/invoices`, `GET /teams/me` (capabilities).

### 7.1 Current plan card

| Show | From |
|---|---|
| Plan name and price | `plan.name`, **`effective_price`** (never `plan.monthly_price`; the locked price wins) |
| "Founding rate locked" chip | `locked_price !== null` |
| Next billing date | `period_end`, or `trial_end` while trialling |
| Usage bars | `GET /allowances`. "Resets on {period_end}" goes on **CHECKS only**. |

### 7.2 Banners (show at most one; this is the priority order)

| Condition | Banner | Action |
|---|---|---|
| `past_due` | "Your last payment failed. Update your card to avoid losing access." | "Update card" → portal |
| `cancel_pending` | "Your plan ends on {cancels_on}." | "Keep my plan" → `POST /subscription/resume` ✅ |
| `scheduled_change` 🔜 | "Moving to {plan} on {effective_on}." | "Keep {current}" → §6.3 |
| `is_trialing` | "{trial_days_remaining} days left in your free trial." Mention adding a card when `trial_days_remaining <= 3`. | "Add card" → portal |

Note: `trial_days_remaining` is `0` when the trial has run out and `null` when there was never a trial. Treat these differently.

### 7.3 Owner vs team

Only the owner has `manage_billing`. Everyone else sees the plan read-only: no Change, Cancel or Card buttons, and a line saying "Managed by the account owner."

### 7.4 Cancel, card and invoices: Stripe Customer Portal

```
POST /api/v1/billing/portal-session      🔜
→ { "url": "https://billing.stripe.com/p/session/…" }
```

`window.location.assign(url)`. The portal returns to `/settings/billing`. On return, **refetch** `GET /subscription`. A cancellation made in the portal shows up as `cancel_pending: true` and `cancels_on`, usually within seconds (it arrives by webhook). If the change isn't visible yet, refetch once more after 3 s.

Use the portal for:
- **Cancel**: "Cancel plan" button. Before redirecting, show a dialog: "You'll keep access until {period_end}."
- **Update card**: past due, or adding a card during a trial.
- **Invoices**: optional. `GET /billing/invoices` ✅ already lists them with PDF links in-app.

In mock mode (`collects_money: false`) there is no portal. Fall back to the existing `DELETE /billing/subscription` ✅ for cancel, and hide the card controls.

---

## 8. Global 402 handler (plan limits and paywall)

Put this in the one fetch wrapper. 402 = "needs a (bigger) plan"; 403 = "role forbids". **Never treat them alike.**

```ts
if (res.status === 402) {
  const { code, message, limit, feature } = body;
  switch (code) {
    case "subscription_required":           // 🔜 no live subscription
      return go(`/pricing`);
    case "plan_limit":                      // ✅ SEATS | BANKS | CHECKS | ENTITIES(🔜)
    case "feature_not_in_plan":             // 🔜 e.g. feature: "1099" | "APPROVAL_WORKFLOW" | "ERP_SYNC"
      return openUpgradeDialog({ message, suggested: cheapestPlanThatLifts(limit ?? feature) });
  }
}
```

- Show `message` **verbatim**. It is written for users.
- `cheapestPlanThatLifts`: compare against `GET /plans` limits (for example `BANKS` → the first plan with `unlimited_banks`), plus the static feature table (1099 → STANDARD; approval workflows and ERP sync → ENTERPRISE with the add-on).
- The upgrade dialog's button opens the change-plan modal (§6) for a subscribed user, or `/checkout?plan=` for one without a subscription.

### 8.1 Feature checks to mirror in the UI (comparison table)

The backend is the authority. The UI only **hides or labels** features up front, so users don't hit a 402.

| Feature | Founding | Standard | Enterprise | UI treatment |
|---|---|---|---|---|
| Team members | 3 | 10 | ∞ | "Invite" shows "2 of 3 seats used". Disable it at the limit and show an upgrade link. |
| Connected banks | 1 | ∞ | ∞ | Before opening Plaid, check `allowances.BANKS.remaining`. If it's 0, show the upgrade prompt instead. |
| Business entities | 1 | 1 | 3 (+$79 each) | "Add entity" is visible only on Enterprise. Beyond 3, the confirm dialog shows "+$79/month". |
| 1099 reporting | ✗ | ✓ | ✓ | Founding: report tab shows a lock icon and "Available on Standard". |
| Approval workflows | ✗ | ✗ | Add-on | Lock icon with "Enterprise add-on" |
| ERP sync | ✗ | ✗ | Add-on | Lock icon with "Enterprise add-on" |
| Mailed checks | 2/mo | 5/mo | 5/mo | Never blocks. After the free ones, the payment quote shows the $2.99 fee. |
| Support | Email | Priority | Dedicated | Help menu copy only |

Read plan state from **one** shared store (`useSubscription()` caching `GET /billing/subscription` and `/allowances`). Invalidate it after any checkout, plan change, portal return, bank link, invite or entity change.

---

## 9. Edge cases checklist

- [ ] Double-clicking "Get Started": disable the button while waiting, and send an `Idempotency-Key`.
- [ ] Two tabs both start checkout: the second gets 400 `already_subscribed` after the first is fulfilled. Go to billing settings.
- [ ] User closes the browser on the Stripe page and logs in later: the post-auth router sees `null` and sends them to checkout again (the backend reuses the open session).
- [ ] Paid, but the webhook is slow: the success page waits and does **not** start a new checkout.
- [ ] Founding spots run out between the pricing page and payment: the success page shows `effective_price`, which may be the list price. Copy says "Your price: $X/month", without promising the lock.
- [ ] Trial already used: Standard CTA shows "Get Started", and Checkout asks for a card.
- [ ] Past due user hits a 402: show the past-due banner, not an upgrade prompt.
- [ ] Teammate without `manage_billing`: never sees checkout or plan-change buttons.
- [ ] `collects_money: false`: the whole flow still works with no card screens.
- [ ] Back button after Stripe redirects: `/checkout` must not auto-redirect again if a subscription now exists. Re-check `GET /subscription` first.

---

## 10. Build order

| Step | Scope | Depends on |
|---|---|---|
| 1 | Pricing page from `GET /plans`, CTA logic, `planIntent` helpers, `?plan=` on register and login | ✅ now |
| 2 | Post-auth router, `useSubscription()` store, global 402 handler (`plan_limit`) | ✅ now |
| 3 | Billing settings: plan card, usage, banners, resume, invoices | ✅ now |
| 4 | `/checkout` and `/billing/success` with polling | 🔜 checkout-session (mock it until then) |
| 5 | Change-plan modal with preview, scheduled-downgrade banner and undo | 🔜 change-preview |
| 6 | Portal button (cancel, card) | 🔜 portal-session |
| 7 | Feature locks (1099, entities, add-ons), `subscription_required` paywall | 🔜 backend phase 4 |

---

## 11. QA with Stripe test mode

| Scenario | Card / setup | Expect |
|---|---|---|
| Founding, paid | `4242 4242 4242 4242` | Success page, then `effective_price` matches `/plans` and `locked_price` is set |
| Standard trial | No card | `is_trialing: true`, 14 days left |
| 3-D Secure | `4000 0025 0000 3155` | Stripe shows the challenge, then success |
| Declined | `4000 0000 0000 0002` | Stays on Stripe's page with an error. No subscription is created. |
| Upgrade mid-cycle | Founding → Standard | Preview amount equals the amount charged; the plan changes immediately |
| Downgrade | Standard → Founding with 2 banks | Preview `fits: false`, button disabled |
| Cancel in portal | — | Back in the app: `cancel_pending: true` and `cancels_on` = `period_end` |
| Payment fails at renewal | Stripe test clock and `4000 0000 0000 0341` | `past_due` banner, and the portal fixes it |
