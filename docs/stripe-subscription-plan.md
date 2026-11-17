# Stripe Subscription — Checkout, Plan Changes, Proration, Feature Gates

Status: **plan, not built** · Owner: billing (`apps/billing`) · Date: 2026-11-14 · Revised: 2026-11-17

Related: [Billing API](billing-api-documentation.md) · [Stripe Treasury plan](stripe-treasury-integration-plan.md)

---

## 0. Decisions needed before Phase 1

| # | Question | Why it matters | Recommendation |
|---|---|---|---|
| D1 ✅ | **Settled: $29.** ~~Founding price: $29 or $49?~~ The pricing page and comparison table say **$29**. `PLAN_SPECS`, the PRD (FR-8.1) and the BRD §6.2 say **$49**. | Stripe charges whatever the plan row holds. Shipping with this mismatch means charging customers more than the page they clicked on. | Product confirms. If it's $29, update the BRD, `PLAN_SPECS`, and add a data migration. `ensure_price` makes a new Stripe Price the first time it runs. No customer has been charged $49 yet. |
| D2 | **Enterprise "Get Started": self-serve checkout at $299, or contact sales?** `PLAN_SPECS` says it is "sales-led and negotiated". | Decides whether Enterprise goes through the Checkout flow at all. | Self-serve at the $299 base, with add-ons added later in-app (`POST /billing/addons`). Negotiated deals get a custom price added from the admin. |
| D3 | **Downgrade timing** | Proration policy (see §4) | Upgrades take effect immediately with a prorated charge. Downgrades take effect at the end of the period with no refund. |
| D4 ⚠️ required | **What can a signed-up user with no subscription do?** With Checkout a user can sign up and back out of the Stripe page, so this is no longer optional. Today `current_plan_code` falls back to FOUNDING, so a user who never paid gets Founding limits. | Without a paywall, Checkout is optional. | Add a hard gate: with no live subscription, the product APIs answer 402 `subscription_required`. Auth, billing, profile and onboarding stay open (§6). |
| D5 | **Plan changes inside the Stripe Customer Portal?** | The portal can't run our "does the account fit the smaller plan" check (402). | No. The portal handles **cancel, card and invoices only**. Plan changes stay in-app through `PATCH /billing/subscription`. |

---

## 1. What already exists

A lot of this is already built. Only the hosted-checkout entry point is missing.

| Capability | Where | Status |
|---|---|---|
| Public plan list with `spots_remaining` and `trial_eligible` | `GET /billing/plans` · `PlanListAPIView` | ✅ |
| Plans, limits and trial days seeded from the BRD | `apps/billing/models/plan.py` `PLAN_SPECS` | ✅ (price D1) |
| Founding price lock for the first 500 customers | `SubscriptionService.subscribe`, `Subscription.locked_price` | ✅ |
| Standard 14-day trial, no card needed, first subscription only | `trial_eligible`, `trial_settings.missing_payment_method=create_invoice` | ✅ |
| Subscribe with a card collected by **SetupIntent / Elements** (embedded, not hosted Checkout) | `POST /billing/payment-method/setup` → `POST /billing/subscription` | ✅ |
| Plan change | `PATCH /billing/subscription` | ⚠️ `proration_behavior: "none"`, applies immediately in both directions |
| Downgrade check: usage must fit the new plan (seats, banks), else 402 | `SubscriptionService._assert_fits` | ⚠️ entities and Enterprise add-ons are not checked |
| Cancel at period end and resume | `DELETE /billing/subscription`, `POST /subscription/resume` | ✅ |
| Replace card, retry past-due invoice | `POST /billing/payment-method` | ✅ |
| Invoice history with PDF links | `GET /billing/invoices` | ✅ |
| Webhook: `invoice.paid/payment_succeeded/payment_failed`, `customer.subscription.updated/deleted` | `apps/billing/api/views/webhook.py` | ⚠️ updates status only; does not sync plan or period |
| 402 ceilings: banks, seats | `link_service`, `team_service` via `AllowanceService` | ✅ |
| Mailed checks 2 or 5 per month, metered | `AllowanceKind.CHECKS` | ✅ |
| 1099 reporting on Standard and up | `reports/api/views/report.py` `has_plan_at_least` | ✅ |
| Enterprise entity add-on ($79/entity above 3) | `entity_service`, `addon_service` | ✅ |

### What's missing

1. **Stripe Checkout Session** (hosted page) and the redirect round trip.
2. **Carrying the selected plan through register/login.** This is mostly the frontend's job (§2).
3. **`checkout.session.completed`** webhook, which creates the local `Subscription`.
4. **Proration**: a preview endpoint, immediate prorated upgrades, and downgrades scheduled for period end.
5. **Customer Portal session**, used for cancel.
6. **A paywall** for accounts with no subscription (D4).
7. A **webhook that syncs the plan and period**, so Stripe and Swayp can't disagree on which plan the account is on.
8. Gaps in the feature gates (§6).

---

## 2. Target flow: from "Get Started" to paid

```
Pricing page ──click plan──▶ /register?plan=STANDARD  (or /login?plan=…)
                                   │
                         auth succeeds (incl. email verify / 2FA)
                                   │
                      GET /billing/subscription
                     ┌─────────────┴──────────────┐
                 has live sub                  null
                     │                            │
          plan == selected?            POST /billing/checkout-session {plan}
          yes → dashboard                         │
          no  → "change plan" UI (PATCH)   302 to session.url (Stripe hosted)
                                                  │
                         ┌────────────────────────┴───────────┐
                    paid / trial started                 user backs out
                         │                                    │
          Stripe → webhook checkout.session.completed   cancel_url → /pricing?plan=…
          (creates Subscription)                      (no sub; paywall still on)
                         │
          success_url → /billing/success?session_id=cs_…
          frontend polls GET /billing/checkout-session/{id} until "complete"
                         │
                     dashboard
```

**How the selected plan survives auth.** The frontend keeps `plan` in the query string and in `sessionStorage`, then sends it through register, verify-email and 2FA. The backend also stores it as `User.profile.intended_plan` (optional `plan` field on `POST /auth/register`). That way a user who verifies their email on another device still lands on the right checkout. If no plan was selected, the user goes to `/pricing` after auth.

**The backend chooses the route, not the button.** The button label ("Get Started" or "Start Free Trial") is display only. Whether a trial applies is the backend's call: `trial_eligible` is false for an account that has subscribed before, so a returning user clicking "Start Free Trial" must pay. The frontend always calls `POST /billing/checkout-session {plan}` and follows the answer:

| Answer | When | Frontend does |
|---|---|---|
| `{ "action": "subscribed", "subscription": {...} }` | Trial applies (`trial_eligible` and `plan.trial_days`) | Go to the dashboard. No Stripe page, no card ("no card needed" stays true). The subscription is created through the existing no-card path. |
| `{ "action": "redirect", "url": "https://checkout.stripe.com/…", "session_id": "cs_…" }` | Anything to pay now (Founding, Enterprise, Standard without a trial) | `window.location = url` |

Trials never go through Checkout.

**Every "pay now" moment uses a Stripe-hosted page.** The goal is that the frontend never builds a card form. Checkout covers the first payment; the other moments are:

| Moment | Hosted page |
|---|---|
| First payment | Checkout Session (§3) |
| Switching from a trial to a plan with no trial (ends the trial and charges now, see §4.1) | The invoice's `hosted_invoice_url`, returned on `PATCH` instead of `client_secret` |
| Trial ended with no card, or a charge failed (PAST_DUE) | Customer Portal (§7) to add a card; it pays the open invoice |
| Add or replace a card any time | Customer Portal (§7) |

The Payment Element / `client_secret` path is then only kept for mobile and older clients.

---

## 3. Phase 1: Checkout Session

### 3.1 Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/billing/checkout-session` | owner (`MANAGE_BILLING`) | Body `{plan}` → `{action: "redirect", url, session_id}` or, when a trial applies, `{action: "subscribed", subscription}` (§2). 400 `already_subscribed` if a live sub exists. |
| GET | `/api/v1/billing/checkout-session/{id}` | owner | `{status: open\|complete\|expired, subscription}`, polled by the success page. |
| POST | `/api/v1/billing/portal-session` | owner | `{url}` to the Stripe Customer Portal (cancel, card, invoices). |

### 3.2 Creating the session (`CheckoutService.create`)

- `customer`: reuse or create through `BillingProviderService.customer_id`. Lift the customer id from `Subscription` onto the account (`User.stripe_customer_id`, or a small `BillingCustomer` model), because no `Subscription` row exists yet at checkout time.
- `mode="subscription"`, `line_items=[{price: price_id(plan), quantity: 1}]`.
- **Founding lock**: if the lock is still available, record `locked_price` in `metadata`. The price is the plan's own price, so no special Stripe price is needed today. If the list price ever changes, locked customers must stay on the **old** Stripe Price id. Keep `provider_price_id` per *price amount*, not per plan, so old prices are never deleted.
- **Trial**: never in a session. When `trial_eligible(account)` and `plan.trial_days`, the endpoint does not create a session at all: it calls `SubscriptionService.subscribe` (no card, `trial_settings.end_behavior.missing_payment_method=create_invoice`) and answers `action: "subscribed"`.
- `metadata` **and** `subscription_data.metadata`: `{account_id, plan_code, locked_price}`. The webhook resolves the account from these, never from the email.
- `client_reference_id=account_id`.
- `success_url=f"{FRONTEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"`, `cancel_url=f"{FRONTEND_URL}/pricing?plan={code}"`.
- `allow_promotion_codes=True` if marketing wants coupons (optional).
- Idempotency: if the account has an **open** session for the same plan that is less than 1 hour old, return it instead of creating another. Store it in a `CheckoutSession` row (`account, plan, stripe_session_id, status, expires_at`).

### 3.3 Fulfilment (webhook `checkout.session.completed`)

- Locate the account from `metadata.account_id`, then retrieve the Stripe subscription.
- Inside one transaction: `select_for_update` on the account. If a live `Subscription` already exists, do nothing (a webhook retry, or a double click across two tabs). Otherwise create a `Subscription` from the Stripe object: plan from the price id, `period_start/end` from `current_period_*`, `trial_end`, `locked_price` (check `founding_lock_available()` **again** here), and the `provider_*` ids.
- Also run on `GET /checkout-session/{id}` when Stripe says `complete` and the webhook hasn't landed yet. Both paths call the same idempotent `fulfil(session_id)`.
- Founding spots are claimed **at fulfilment**, not when the session is created. At the 500 boundary a few checkouts may complete at once. Each one gets the lock only if a spot is left at fulfilment, otherwise list price. The pricing page counter is "best effort". *(Phase 0 fix: `founding_seats_taken` counts current `plan=FOUNDING` rows, so a founder who upgrades frees their spot and the number goes back up. Count `locked_price IS NOT NULL` claims instead.)*

### 3.4 What happens to the old SetupIntent subscribe path

Keep `POST /billing/subscription` working for mobile and for existing clients, and mark it **deprecated for web** in the docs. Both paths end in the same `Subscription` shape.

---

## 4. Phase 2: Upgrade, downgrade, proration

### 4.1 Rules

| Change | Takes effect | Money | Validation |
|---|---|---|---|
| **Upgrade** (Founding→Standard, *→Enterprise) | Immediately | Prorated difference is charged **now** (`proration_behavior="always_invoice"`). If the charge fails the plan doesn't change (`payment_behavior="pending_if_incomplete"`) | None. A bigger plan always fits. |
| **Downgrade** (Enterprise→Standard, *→Founding) | At `period_end` | No refund, no credit. The customer keeps what they paid for until then. | `_assert_fits` at request time **and again** when it takes effect |
| **During a trial, to a plan with a trial** | Immediately | Nothing charged. Billing starts at `trial_end` at the new plan's price | Same fit check for downgrades |
| **During a trial, to a plan with no trial** (Founding, Enterprise) | Immediately; **the trial ends** | The new price is charged now and a new cycle starts today. With no card on file, `PATCH` returns `hosted_invoice_url` to pay. *(Built in `d60fc28`, which returns `client_secret` today; switch it to `hosted_invoice_url`.)* | Same fit check. Moving onto Founding claims the lock while spots remain. |
| **Same plan** | Nothing happens | — | — |
| **Back to Founding** | — | Locked price **only** if a founding spot is still free. Otherwise list price. Leaving Founding gives up the lock (current rule, kept). | — |

### 4.2 Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/billing/subscription/change-preview?plan=X` | `{direction: upgrade\|downgrade, effective: "now"\|"2026-12-01", amount_due_now, next_invoice_total, fits: bool, over: [{limit, used, allowed}]}` |
| PATCH | `/billing/subscription` `{plan}` | **Behaviour changes**: upgrade → 200 with the new plan. Downgrade → 200 with `scheduled_change: {plan, effective_on}` and the current plan unchanged. |
| DELETE | `/billing/subscription/scheduled-change` | Withdraw a pending downgrade |

`change-preview` calls Stripe `invoices.create_preview` with `subscription_details.items` and `proration_date`, so the frontend shows the exact amount Stripe will charge. It never computes the amount itself.

### 4.3 Implementation

- **Provider** (`stripe_provider.py`):
  - `change_plan` gets `proration_behavior` and `payment_behavior` parameters, replacing the hard-coded `"none"`.
  - New `preview_change(subscription_id, price_id)`.
  - New `schedule_change(subscription_id, price_id, at=current_period_end)` using **Subscription Schedules** (`subscription_schedules.create(from_subscription=…)`, two phases). Stripe then bills the lower price at renewal without a cron on our side.
  - New `release_schedule(schedule_id)`.
- **Model** (`Subscription`): `scheduled_plan` (FK, null), `scheduled_change_on` (date, null), `provider_schedule_id`. Add them in a migration.
- **Service** (`SubscriptionService.change_plan`): branch on `PLAN_ORDER` rank. Upgrade calls the provider first and updates locally **after** Stripe accepts the charge. This reverses today's order on purpose, because the customer should never get the upgrade without paying for it. Downgrade validates, then schedules.
- **Pending downgrade and capacity.** While a downgrade is pending, the capacity checks (`AllowanceService.check_capacity`) use the **lower** of the current and scheduled limits. Otherwise the user could add a 2nd bank the day after scheduling a move to Founding.
- **Applying it**: the `customer.subscription.updated` webhook sees the new price and syncs `plan` (see §5). The nightly renewal task also checks `scheduled_change_on <= today` as a fallback for the mock provider.
- **Over the limit when the downgrade takes effect.** Normally this can't happen because of the rule above. If it still does, apply the plan anyway, because Stripe has already billed the lower price. New adds then get a 402 until usage is under the limit. Nothing that already exists is deleted.

---

## 5. Phase 3: Webhook hardening

Add to `HANDLED`:

| Event | Action |
|---|---|
| `checkout.session.completed` | `fulfil()` (§3.3) |
| `checkout.session.expired` | Mark the `CheckoutSession` row expired |
| `customer.subscription.created` | Do nothing if it's already fulfilled. Otherwise fulfil from `metadata` (a safety net) |
| `customer.subscription.updated` | **Also** sync `plan` (from `items.data[0].price.id` → `Plan`), `period_start/end`, `trial_end`, `cancel_at_period_end` → `cancels_on`, and the schedule fields. It updates status only today. |
| `customer.subscription.deleted` | Already handled: CANCELLED |
| `customer.subscription.trial_will_end` | Email "trial ends in 3 days, add a card" (`notifications`) |
| `invoice.payment_action_required` | Email with the hosted invoice URL (3-D Secure) |
| `subscription_schedule.released/canceled` | Clear `scheduled_plan` |

Also:
- **Dedupe table** `BillingWebhookEvent(event_id unique, type, processed_at)`. Stripe retries, and creating a subscription must never happen twice.
- Ordering: compare `event.created` to the last applied one per subscription, so an older `subscription.updated` can't overwrite a newer one.
- Replace `PROVIDER_STATUS_MAP["incomplete"]="ACTIVE"` for **Checkout-born** subs. Checkout only completes once paid, so `incomplete` there means something unexpected. Log a warning.

---

## 6. Phase 4: Feature validation from the comparison table

| Row | Founding | Standard | Enterprise | Enforced today? | Work |
|---|---|---|---|---|---|
| Monthly price | $29* | $99 | $299 | Plan row | D1 |
| Bills & vendors | ∞ | ∞ | ∞ | No gate (correct) | — |
| Team members | 3 | 10 | ∞ | ✅ 402 `SEATS` | — |
| Connected banks | 1 | ∞ | ∞ | ✅ 402 `BANKS` | — |
| Business entities | 1 | 1 | 3 (+$79 each) | ⚠️ `entity_service.assert_can_add`. Check that non-Enterprise plans get a 402 `ENTITIES` at 2 | Add `AllowanceKind.ENTITIES` to `overages_for_plan`, so a downgrade from Enterprise with 2+ entities is refused |
| QR bill processing | ✓ | ✓ | ✓ | No gate | — |
| Manual bill entry | ✓ | ✓ | ✓ | No gate | — |
| 1099 reporting | ✗ | ✓ | ✓ | ✅ `has_plan_at_least(STANDARD)` | Return 402 `feature_not_in_plan` with `feature: "1099"` (check it uses the 402 shape, not 403) |
| Approval workflows | ✗ | ✗ | Add-on | ❌ The feature isn't built | Add `has_addon(account, APPROVAL_WORKFLOW)` helper in `apps/common/plans.py`, so the gate exists before the feature (same approach as the 1099 gate) |
| Advanced ERP sync | ✗ | ✗ | Add-on | ❌ The feature isn't built | Same helper, `ERP_SYNC` |
| Mailed checks | 2/mo | 5/mo | 5/mo | ✅ metered, $2.99 overage | — |
| Standard bank transfers | Free | Free | Free | ✅ fee service | — |
| Customer support | Email | Priority | Dedicated | Not code-enforced | Expose `support_tier` on `GET /plans` and `GET /subscription` |

Also:
- **Downgrade from Enterprise** (`_assert_fits`): refuse it if entities > 1. Active add-ons are removed when the downgrade takes effect, and the preview lists them (`removes_addons: [...]`).
- **Paywall (D4)**: a DRF permission `HasLiveSubscription`, applied by default to the product apps (bills, vendors, payments, banking, teams, reports). It is **not** applied to `auth`, `users`, `billing` or `webhooks`. With no live subscription it answers 402 `subscription_required` with `limit: null`, and the existing global 402 handler sends the user to `/pricing`. PAST_DUE keeps access (current rule). CANCELLED loses it.
- **402 codes in one place**: `plan_limit` (existing), plus `feature_not_in_plan` and `subscription_required`, defined in `apps/common/error_codes.py`.

---

## 7. Phase 3b: Stripe Customer Portal (cancel, card, unpaid invoices)

Moved up from last: with no card screen in the app, the portal is where a user adds a card after a no-card trial and pays a PAST_DUE invoice.

- Portal configuration (created once by a management command, `manage.py stripe_setup_portal`, so it's versioned rather than set by hand in the dashboard):
  - `subscription_cancel.enabled=true`, `mode=at_period_end`, `cancellation_reason.enabled=true`
  - `subscription_update.enabled=false` (D5)
  - `payment_method_update.enabled=true`, `invoice_history.enabled=true`
- `return_url = {FRONTEND_URL}/settings/billing`.
- The webhook `customer.subscription.updated` (`cancel_at_period_end=true`) sets `cancels_on`, and `customer.subscription.deleted` sets CANCELLED. Both are handled in §5.
- Keep `DELETE /billing/subscription` and `/resume` for the mock provider and mobile. On web, the "Cancel plan" button opens the portal.

---

## 8. Configuration

```env
SUBSCRIPTION_BILLING_PROVIDER=stripe
STRIPE_SECRET_KEY=sk_test_…
STRIPE_PUBLISHABLE_KEY=pk_test_…
STRIPE_BILLING_WEBHOOK_SECRET=whsec_…
STRIPE_PORTAL_CONFIGURATION_ID=bpc_…   # written by stripe_setup_portal
FRONTEND_URL=https://app.swayp.com     # success/cancel/return URLs
```

Webhook endpoint events (Stripe dashboard): the full list in §5.

With the mock provider, `POST /checkout-session` returns `url = {FRONTEND_URL}/billing/success?session_id=mock_…` and fulfils immediately, so local development and tests don't need Stripe.

---

## 9. Tests (pytest, `apps/billing/tests/`)

- `test_checkout_session.py`:
  - creates a session with the right price and metadata
  - a trial-eligible Standard answers `subscribed` with no session; a returning account on Standard answers `redirect`
  - reuses an open session
  - 400 when already subscribed
  - no trial on a second subscription
  - Founding lock is decided at fulfilment, not at session creation
- `test_checkout_fulfilment.py`:
  - webhook and poll race leaves exactly one Subscription
  - a duplicate event id is ignored
  - account is resolved from metadata, not email
- `test_plan_change_proration.py`:
  - upgrade charges now, and the plan stays unchanged when payment fails
  - downgrade is scheduled and the plan stays unchanged until the effective date
  - a pending downgrade lowers capacity
  - withdrawing a scheduled downgrade works
  - downgrade during a trial
  - leaving Founding loses the lock
- `test_feature_gates.py`:
  - entities 402
  - 1099 402 `feature_not_in_plan`
  - add-on gates
  - paywall 402 `subscription_required` on product endpoints only
- `test_webhook_sync.py`:
  - `subscription.updated` syncs plan and period
  - out-of-order events are ignored
  - portal cancel sets `cancels_on`
- Stripe calls are mocked at the `stripe_provider` boundary, as `test_stripe_billing.py` does today. Add one opt-in live test-mode smoke test (`-m stripe_live`).

---

## 10. Order of work

| Phase | Scope | Size |
|---|---|---|
| 0 | Settle D2 (Enterprise self-serve or sales) and D3/D5. Build the paywall (D4). Fix `founding_seats_taken` | S–M |
| 1 | Checkout Session with the two-answer response (§2), fulfilment, success polling, `intended_plan` on register | M |
| 3 | Webhook dedupe and plan/period sync (Phase 1 depends on it, so do it alongside) | S |
| 3b | Customer Portal, and `hosted_invoice_url` on the trial→paid switch: removes the remaining Payment Element uses | S |
| 2 | Proration: preview, immediate upgrade, scheduled downgrade | M |
| 4 | Feature gates, entity downgrade check | M |
| — | Update `billing-api-documentation.md` (§3, §10, §11 "No proration") and `frontend-integration-guide.md` | S |
