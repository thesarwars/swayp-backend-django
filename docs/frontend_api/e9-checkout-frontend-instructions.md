# Frontend instructions: Stripe Checkout, portal, paywall

What the web app has to change for the new billing flow. The app **never
shows a card form**: Stripe hosts every payment page.

Full reference, with every response body: [E9b Subscription frontend plan](e9-subscription-frontend-plan.md).

---

## 1. What changed in the API

| Method | Path | Who | Use |
|---|---|---|---|
| POST | `/api/v1/billing/checkout-session` | owner | **Every plan button.** Starts a trial, or returns a Stripe Checkout URL |
| GET | `/api/v1/billing/checkout-session/{session_id}` | owner | Success page polls it until `complete` |
| POST | `/api/v1/billing/portal-session` | owner | Stripe Customer Portal URL: card, invoices, cancel |
| PATCH | `/api/v1/billing/subscription` | owner | Change plan. **New:** may return `payment_url` |
| any | product endpoints | everyone | **New:** `402 subscription_required` when the account has no plan |

**Stop using on web:** `POST /billing/subscription`,
`POST /billing/payment-method/setup`, `POST /billing/payment-method`,
`client_secret` and the Stripe Payment Element. They are kept for mobile only.
Remove `@stripe/react-stripe-js` card screens from the web app.

---

## 2. Plan buttons (pricing page and `/subscribe?plan=CODE`)

The button label comes from `GET /billing/plans`:

- `trial_eligible && trial_days > 0` → "Start Free Trial"
- otherwise → "Get Started"

**The label is display only. The backend decides the route.** All buttons
call the same endpoint:

```ts
async function startPlan(plan: "FOUNDING" | "STANDARD" | "ENTERPRISE") {
  const res = await api.post(
    "/billing/checkout-session",
    { plan },
    { headers: { "Idempotency-Key": crypto.randomUUID() } }, // one per click
  );
  const data = res.data;

  if (data.action === "subscribed") {
    // A trial started. No payment, no card, no Stripe page.
    clearPlanIntent();
    await refreshSubscription();
    return go("/onboarding"); // or /dashboard
  }

  // action === "redirect": leave the app for Stripe's payment page.
  window.location.href = data.url;
}
```

- Disable the button while the request runs.
- A user who isn't signed in goes to `/register?plan=CODE` first; after
  sign-in, call `startPlan` (see "Remembering the selected plan" in E9b §3).

| Error | Show |
|---|---|
| 400 `already_subscribed` | Go to `/settings/billing` (use change plan there) |
| 403 `role_forbidden` | "Only the account owner can choose a plan" |
| 503 | "Billing is temporarily unavailable. You have not been charged." + Retry |

---

## 3. New page: `/billing/success`

Stripe sends the browser here after payment:
`/billing/success?session_id=cs_test_…`

```ts
const sessionId = new URLSearchParams(location.search).get("session_id");

async function poll(started = Date.now()) {
  const s = (await api.get(`/billing/checkout-session/${sessionId}`)).data;

  if (s.status === "complete") {
    clearPlanIntent();
    await refreshSubscription();
    return go("/onboarding"); // or /dashboard
  }
  if (s.status === "expired") return go(`/pricing?plan=${s.plan}`);
  if (Date.now() - started > 30_000) return showConfirmingWithRefresh();

  setTimeout(() => poll(started), 2000);
}
```

- Show "Confirming your payment…" while polling. It's usually complete on
  the first or second call.
- **Never start checkout again from this page.**
- 404 → go to `/pricing`.
- `subscription.locked_price` is `null` if the Founding spots ran out while
  the user was paying. Don't promise the founder rate in that case.

**If the user backs out of Stripe**, Stripe sends them to `/pricing?plan=CODE`.
Nothing was created; just show the pricing page again.

---

## 4. Paywall: handle `402 subscription_required`

An account with no live plan gets 402 on every product endpoint (bills,
vendors, payments, banks, team, reports, dashboard). Add this to the global
fetch wrapper, **before** the existing `plan_limit` branch:

```ts
if (res.status === 402 && body.code === "subscription_required") {
  return isOwner ? go("/pricing") : go("/no-plan");
}
if (res.status === 402 && body.code === "plan_limit") {
  // existing upgrade dialog (body.limit: "SEATS" | "BANKS")
}
```

- Still open without a plan: `/billing/*`, `/users/profile`, onboarding,
  `GET /teams/me`.
- A trial and a past-due plan keep access. A cancelled plan loses it.
- `/no-plan` (new, for teammates): "Your account owner needs to choose a
  plan." `isOwner` = `GET /teams/me` → `capabilities` includes
  `manage_billing`.

**After sign-in**, route like this (replaces the old router):

```ts
const sub = (await api.get("/billing/subscription")).data; // null = no plan
if (!sub) return isOwner ? (plan ? startPlan(plan) : go("/pricing")) : go("/no-plan");
```

---

## 5. Billing settings: card, invoices, cancel → Customer Portal

Replace the card form with one button, "Manage card & invoices":

```ts
const { url } = (await api.post("/billing/portal-session")).data;
window.location.href = url; // Stripe returns to /settings/billing
```

Use it for:

| Banner / button | Condition |
|---|---|
| "Your last payment failed. Update your card." → **Update card** | `past_due` |
| "{n} days left in your trial. Add a card to continue." → **Add card** | `is_trialing` (stress it when ≤ 3 days) |
| **Manage card & invoices** | always, for the owner |

When the user comes back to `/settings/billing`, refetch
`GET /billing/subscription`.

Cancel and resume can stay on the in-app buttons
(`DELETE /billing/subscription`, `POST /billing/subscription/resume`); the
portal can also cancel. **Plan changes stay in the app**; the portal can't
change plans.

---

## 6. Change plan: new `payment_url`

`PATCH /billing/subscription { plan }` is unchanged, except in one case:
**during a trial, switching to a plan without a trial (Founding, Enterprise)
ends the trial and charges now.**

- Confirm dialog copy for that case: "Founding has no free trial.
  Switching ends your trial and charges $29 today."
- If the response has a non-empty `payment_url`, no card was on file:
  `window.location.href = payment_url` (Stripe's hosted invoice page).
  Until it's paid, `past_due` is `true` and the past-due banner shows.

---

## 7. Local development

With the mock provider (`GET /billing/config` → `collects_money: false`):

- `checkout-session` returns `url` = `/billing/success?session_id=…`, already
  `complete`. The full round trip works with no Stripe page.
- `portal-session` returns `url` = `/settings/billing`.

---

## 8. Test in Stripe test mode

| Scenario | Card (on Stripe's page) | Expect |
|---|---|---|
| Standard, first time | none | `subscribed`, no Stripe page, 14-day trial |
| Founding | `4242 4242 4242 4242` | Stripe page → `/billing/success` → `complete`, `locked_price` set |
| 3-D Secure | `4000 0025 0000 3155` | Challenge on Stripe's page, then success |
| Declined | `4000 0000 0000 0002` | Stripe shows the error; nothing created in Swayp |
| Backed out | — | Back on `/pricing`; product pages return 402 `subscription_required` |
| Standard again after cancelling | `4242…` | Button says "Start Free Trial" but the answer is `redirect` (no second trial) |
| Trial → Founding, no card | — | `PATCH` returns `payment_url`; paying it clears `past_due` |
| Teammate, no plan | — | `/no-plan` |

---

## 9. Checklist

- [ ] All plan buttons call `POST /billing/checkout-session` and follow `action`
- [ ] `/billing/success` page with polling
- [ ] Global 402 handler: `subscription_required` → `/pricing` or `/no-plan`
- [ ] `/no-plan` page for teammates
- [ ] Post-sign-in router uses `startPlan`
- [ ] Card form removed; "Manage card & invoices" opens the portal
- [ ] Past-due and trial banners open the portal
- [ ] Change-plan dialog: trial → Founding/Enterprise copy, and `payment_url` redirect
- [ ] Payment Element, SetupIntent and `client_secret` code removed from web
