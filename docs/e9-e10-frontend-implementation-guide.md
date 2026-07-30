# E9 + E10 — Frontend Implementation Guide

What shipped in **Billing** and **Teams**, and how to build against it.

This is the *how to build it* guide. Per-endpoint reference lives in
[Billing API](billing-api-documentation.md) and [Teams API](teams-api-documentation.md);
this one is about screens, order, and the traps that cost a day.

Every response below was captured from the running API.

---

## 1. What actually shipped

**E9 — Billing.** Three plans, per-plan allowances (seats, banks, free
checks), per-transaction fees, automatic refunds when a delivery guarantee is
missed, Enterprise add-ons, and a derived invoice preview.

**E10 — Teams.** Team members with per-plan seat limits, email invitations,
three roles with a capability matrix, and multi-entity accounts for Enterprise.

**One consequence ties them together:** an account is now a *workspace*, not a
person. Bills, vendors, payments, banks and the subscription belong to the
account, and everyone on the team sees the same data.

⚠️ **Stripe is wired, but whether it charges depends on configuration.**
`POST /billing/payment-method/setup/` returns `collects_money`. When it is
`false` the deployment records entitlements and charges nothing — skip the
card form. When `true`, collect a card and pass `payment_method_id` to the
subscribe call. The shapes are identical either way, so one build serves both.
Full flow: [Stripe Billing Setup](stripe-billing-setup.md).

---

## 2. The four ideas to hold in your head

Get these wrong and the UI will be subtly wrong everywhere.

### 2.1 The account is not the user

After someone accepts an invitation, their requests operate on the **inviting
account**. `GET /teams/me/` tells you which:

```json
{ "account_id": "649ac658-…", "is_owner": false, "role": "MEMBER",
  "capabilities": ["manage_bills", "manage_vendors", "view"] }
```

Store `account_id` alongside the token. It is the cache key for everything —
if you key caches on the user id, two teammates will thrash each other's data.

### 2.2 Capabilities, not roles

Render off the `capabilities` array. Never write `if (role === 'ADMIN')` — the
matrix can change server-side and a hardcoded check needs a client release to
catch up.

| Capability | OWNER | ADMIN | MEMBER |
|---|:---:|:---:|:---:|
| `view` | ✅ | ✅ | ✅ |
| `manage_bills` | ✅ | ✅ | ✅ |
| `manage_vendors` | ✅ | ✅ | ✅ |
| `send_money` | ✅ | ✅ | — |
| `manage_banks` | ✅ | ✅ | — |
| `manage_team` | ✅ | ✅ | — |
| `manage_entities` | ✅ | ✅ | — |
| `manage_billing` | ✅ | — | — |

A member can *prepare* a payment but not authorize it. Only the owner touches
billing, because a plan change changes what the owner is charged.

Hiding a button is not security — the API checks every action itself. Hide it
anyway, so nobody is offered something that will fail.

### 2.3 402 and 403 are different problems ⚠️

The single most valuable distinction in these two epics.

| | Means | Show | Fixed by |
|---|---|---|---|
| **402** | the plan is full | upgrade prompt | money |
| **403** | your role forbids it | "ask your admin" | nothing |

Sending a 403 to the pricing page is a dead end. Sending a 402 to "ask your
admin" hides a sale. Both carry `message` only — **no `errors` object** — and
both messages are written to be displayed verbatim.

```json
{ "success": false,
  "message": "Your Founding plan allows 3 seats. Upgrade to add more." }
```

```json
{ "success": false, "message": "Your role does not allow this action." }
```

### 2.4 `limit: null` means unlimited, not zero

```json
"BANKS": { "limit": null, "unlimited": true, "used": 1, "remaining": null }
```

`remaining` is `null` too. Branch on `unlimited` — `!limit` cannot tell `null`
from `0`, and those are opposite answers.

---

## 3. Wire the fetch layer first

Do this before any screen. Both epics assume it.

```js
// One place, because 402 and 403 arrive from whichever endpoint performs
// the action — never from /billing/ or /teams/ themselves.
async function api(path, options = {}) {
  const res = await fetch(`/api/v1${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...authHeader(), ...options.headers },
  });

  if (res.status === 402) {
    const { message } = await res.json();
    showUpgradeDialog(message);         // message is display-ready
    throw new PlanLimitError(message);
  }

  if (res.status === 403) {
    const { message } = await res.json();
    showPermissionToast(message);       // NOT the pricing page
    throw new PermissionError(message);
  }

  const body = await res.json();
  if (!res.ok) throw new ApiError(body.message, body.errors);

  // Three envelopes exist across the API — see the Frontend Guide §1.1.
  return body.data !== undefined ? body.data
       : body.items !== undefined ? body.items
       : body;
}
```

**Session bootstrap**, once, right after login:

```js
const me = await api('/teams/me/');
session.accountId    = me.account_id;
session.role         = me.role;
session.capabilities = new Set(me.capabilities);

export const can = (c) => session.capabilities.has(c);
```

---

## 3b. Resuming onboarding

```
GET /api/v1/users/onboarding/
```

```json
{ "total_steps": 5, "designed_steps": 4, "current_step": 3,
  "complete": false,
  "steps": [
    { "step": 1, "key": "business", "complete": true },
    { "step": 2, "key": "plan",     "complete": true },
    { "step": 3, "key": "payment",  "complete": false },
    { "step": 4, "key": "bank",     "complete": false,
      "skipped": false, "skippable": true }
  ] }
```

**Send the user to `current_step`.** It is `null` once nothing is
outstanding. Derived from the real data each step creates, so it cannot drift
— a bank connected later from Settings completes step 4 without the wizard
being involved.

`POST /api/v1/users/onboarding/skip-bank/` records "Skip for now". That is the
one thing that cannot be derived: declining a step leaves no trace, and
without it the wizard would return the user to a step they refused on every
sign-in. A skipped step reports `skipped: true` with `complete: false`, so you
can still offer it again later.

> `designed_steps` is 4 while `total_steps` is 5 — the progress bar says five
> and the fifth has never been specified. Render "of 5" from `total_steps`.

---

## 4. Build order

Each step has real data by the time you reach it.

```
1. Session bootstrap      GET /teams/me/
2. Pricing page           GET /billing/plans/
3. Subscribe              POST /billing/subscription/
4. Billing screen         GET /billing/subscription/ + /allowances/
5. Team screen            GET /teams/members/  → invite → accept
6. Fees + invoice         GET /billing/fees/ + /invoice/
7. Entities (Enterprise)  GET /teams/entities/
```

---

## 5. Screen: Pricing

```
GET /api/v1/billing/plans/
```

Returned sorted by price ascending, so **array order is display order**.

```json
[
  { "code": "FOUNDING", "name": "Founding", "monthly_price": "49.00",
    "seat_limit": 3, "bank_limit": 1,
    "unlimited_seats": false, "unlimited_banks": false,
    "free_checks_per_month": 2, "included_entities": 1, "price_locked": true },
  { "code": "STANDARD", "name": "Standard", "monthly_price": "99.00",
    "seat_limit": 10, "bank_limit": null,
    "unlimited_seats": false, "unlimited_banks": true,
    "free_checks_per_month": 5, "included_entities": 1, "price_locked": false },
  { "code": "ENTERPRISE", "name": "Enterprise", "monthly_price": "299.00",
    "seat_limit": null, "bank_limit": null,
    "unlimited_seats": true, "unlimited_banks": true,
    "free_checks_per_month": 5, "included_entities": 3, "price_locked": false }
]
```

Use `unlimited_seats` / `unlimited_banks` for the "Unlimited" pill rather than
testing the null yourself.

> **`price_locked: true` is a property of the plan, not the customer.** It
> means Founding *offers* a lock. Whether *this* customer has one is
> `subscription.locked_price`.

**Seat copy:** Founding is 3 seats **including the owner**, so a new customer
can invite 2 people. Write "3 users" or "you + 2 teammates" — never "3
teammates".

---

## 5b. Screen: Card collection

Only when `collects_money` is `true`.

```
POST /api/v1/billing/payment-method/setup/
```

```json
{ "client_secret": "seti_..._secret_...",
  "publishable_key": "pk_test_...",
  "collects_money": true }
```

Mount Stripe Elements with `publishable_key`, confirm the SetupIntent with
`client_secret`, and send the resulting `payment_method_id` to
`POST /billing/subscription/`. The card never reaches Swayp.

### The subscribe response can ask for one more step ⚠️

```json
{ "id": "…", "status": "ACTIVE", "client_secret": "pi_..._secret_..." }
```

A non-empty `client_secret` means the bank wants 3-D Secure. **Confirm it with
Stripe.js.** Ignoring it leaves the subscription unpaid at Stripe even though
Swayp shows `ACTIVE` — the entitlement is granted immediately so the customer
is not locked out mid-prompt, but the money has not moved.

A declined card is a **400**, not a 402 — no upgrade fixes it:

```json
{ "errors": { "payment_method_id": "Your card was declined." } }
```

---

## 6. Screen: Billing

Two calls, both safe for anyone on the team to read:

```js
const [subscription, allowances] = await Promise.all([
  api('/billing/subscription/'),
  api('/billing/allowances/'),
]);
```

`GET /billing/subscription/` returns **`null`**, not 404, when there is none —
"this account has no subscription" is a normal answer.

```json
{
  "id": "2f6e31a2-…",
  "plan": { "code": "FOUNDING", "name": "Founding", "monthly_price": "49.00", "…": "…" },
  "status": "ACTIVE",
  "period_start": "2026-07-29",
  "period_end": "2026-08-29",
  "locked_price": "49.00",
  "effective_price": "49.00"
}
```

### Which price to display ⚠️

Three fields, easy to confuse:

| Field | Means |
|---|---|
| `plan.monthly_price` | today's list price |
| `locked_price` | what this customer locked, or `null` |
| `effective_price` | **what they actually pay** |

**Always render `effective_price`.** It is correct whether or not a lock
exists, and it cannot drift when list prices move.

`plan` is nested in full, so no second request.

### The allowances panel

```json
{
  "CHECKS": { "limit": 2, "unlimited": false, "used": 0, "remaining": 2 },
  "SEATS":  { "limit": 3, "unlimited": false, "used": 2, "remaining": 1 },
  "BANKS":  { "limit": 1, "unlimited": false, "used": 1, "remaining": 0 }
}
```

| Kind | Resets? | At the limit |
|---|---|---|
| `CHECKS` | **yes**, at `period_end` | never blocks — bills $2.99 |
| `SEATS` | no | 402 on invite |
| `BANKS` | no | 402 on bank connect |

**Only show "resets on `period_end`" against CHECKS.** Saying it about seats
or banks would be a lie — the banks you connected last month are still
connected.

`used` can exceed `limit` for CHECKS; that is what an overage is. `remaining`
floors at 0, so the overage count is `used - limit`, never `-remaining`.

**These numbers agree with the gate.** `SEATS.used` is counted from the actual
team members and `BANKS.used` from the actual connections, so when `remaining`
is 0 the button really will 402. **Refetch after any invite, removal, connect
or disconnect** and trust it.

### Owner-only writes

`POST` / `PATCH` / `DELETE` on `/billing/subscription/` and `POST
/billing/addons/` need `manage_billing` — **owner only, not even admin**.

```js
{ can('manage_billing') && <ChangePlanButton /> }
```

Downgrading away from Founding **gives up the price lock permanently**.
Warn before submit when `locked_price !== null`:

> "You'll lose your locked $49/mo rate. Coming back later means today's price."

---

## 7. Screen: Team

```
GET /api/v1/teams/members/
```

The owner is always in the list. `REMOVED` members are not.

```json
[
  { "id": "a3a60e69-…", "email": "owner@example.com", "name": "Dana Reed",
    "role": "OWNER", "status": "ACTIVE",
    "capabilities": ["manage_banks", "manage_billing", "…"],
    "invite_expired": false, "invite_expires_at": null,
    "accepted_at": "2026-07-29T09:50:44.372859Z" },
  { "id": "4174b528-…", "email": "lee@example.com", "name": null,
    "role": "MEMBER", "status": "INVITED",
    "capabilities": ["manage_bills", "manage_vendors", "view"],
    "invite_expired": false,
    "invite_expires_at": "2026-08-12T09:50:44.747249Z",
    "accepted_at": null }
]
```

**`name` is `null` until accepted** — there is no user behind the address yet.
Render the email, not an empty string.

Row states to design for: `ACTIVE`, `INVITED`, and `INVITED` with
`invite_expired: true` (offer "resend").

> **There is no invite token in this response, by design.** It is a bearer
> credential and lives only in the invitee's inbox. There is no "copy invite
> link" button to build.

### Inviting

```
POST /api/v1/teams/invite/     { "email": "sam@example.com", "role": "ADMIN" }
```

**201.** The seat is taken immediately — a pending invite counts against
`SEATS.used`. That is deliberate: otherwise an owner could send thirty invites
on a 3-seat plan and the failure would land on the thirty-first *invitee*
rather than on the buyer.

Refetch allowances after a successful invite.

**402** when the plan is full — show the upgrade dialog with the message.

### Re-sending

The same `POST` with an address that is already pending reissues the token and
resends the email, returning **201 with the same `id`**.

⚠️ **Omit `role` when re-sending.** It then keeps the role already chosen.
Sending `role` changes it on purpose.

### Accepting

The emailed link points at *your* route: `FRONTEND_URL/teams/accept?token=…`.

```
POST /api/v1/teams/invite/accept/     { "token": "…" }
```

**The invitee must be signed in first** — the token identifies the invitation,
not the person. So the accept page is:

```
/teams/accept?token=X
   ↓ not signed in? → login/register, preserving ?token=X
   ↓ signed in
POST /teams/invite/accept/ { token }
   ↓ 200
re-run GET /teams/me/   ← their account_id just changed
   ↓
redirect to dashboard
```

**Re-running `/teams/me/` is not optional.** They were their own account a
moment ago; now they are on someone else's.

Every failure is a 400 with a displayable message:

| Cause | Message |
|---|---|
| Unknown / already used | `"This invitation is not valid."` |
| Expired (14 days) | `"This invitation has expired. Ask for a new one."` |
| Signed in as someone else | `"This invitation was sent to a different address."` |
| Owner downgraded meanwhile | `"This team is now full. Ask the account owner to upgrade their plan."` |

That last one is real: the owner can change plan between sending and
accepting, and the seat is re-checked at accept time.

### Role change and removal

```
PATCH  /api/v1/teams/members/<id>/     { "role": "ADMIN" }
DELETE /api/v1/teams/members/<id>/
```

Both **200**. DELETE sets `status: "REMOVED"` and frees the seat immediately —
history survives. The owner cannot be removed or re-roled (400).

---

## 8. Fees, and the refund that must stay visible

Four things a payment can cost. All chosen on `POST /api/v1/payments/`:

| Rail | Requested with | Fee | Guaranteed? |
|---|---|---|---|
| Standard ACH | `rail: "ACH_STANDARD"` | free | — |
| Same-day ACH | `rail: "ACH_SAMEDAY"` | **$4.99** before cutoff only | yes |
| Standard check | `rail: "CHECK"` | free to allotment, then **$2.99** | no |
| Expedited check | `rail: "CHECK"` + `expedited: true` | **$8.99** always | yes |

⚠️ **After the daily cutoff (11:59 PM Eastern) same-day is withdrawn, not
sold.** No fee, no row. **Hide or disable the same-day option after cutoff**
rather than offering something that cannot be delivered.

`expedited` is CHECK-only; any other rail is a 400, not a silent downgrade.
It cuts check transit from 5 business days to 2, so a bill too close to its
due date for a standard check can still land on time.

### The ledger

```
GET /api/v1/billing/fees/
```

```json
[
  { "id": "ec0e143a-…", "kind": "SAME_DAY_ACH", "amount": "4.99",
    "state": "REFUNDED", "payment_reference": "SWP-20260801-0000",
    "guaranteed_arrival": "2026-07-29",
    "refunded_at": "2026-07-29T08:54:46.555733Z",
    "refund_reason": "Delivery guarantee missed" }
]
```

`payment_reference` is the same `SWP-…` on the payment receipt, so a fee links
straight back to what caused it.

**On a refund, `amount` does not change — `state` does.** Do not sum `amount`
to get what is owed; use the invoice.

**Never compute "this looks late, so it must be refunded" on the client.** The
guarantee is judged at *arrival*, so a fee can sit `PENDING` past its
`guaranteed_arrival` and still refund later. Poll the ledger, or wait for the
notification (`type: "PAYMENT"`, with `fee_charge_id` in `metadata`).

---

## 9. Screen: Invoice

```
GET /api/v1/billing/invoice/
```

Derived on read, so always current. Line order is fixed and safe to render
as-is: plan, then add-ons by kind, then fees oldest-first.

```json
{
  "plan": "ENTERPRISE",
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
  "subtotal": "608.99",
  "currency": "USD"
}
```

### Render `total`, not `unit_price` ⚠️

Look at the refunded line: `unit_price: "4.99"`, `total: "0.00"`.

The line stays on the invoice deliberately — dropping it would hide the fact
that Swayp honoured its guarantee. The customer should see the promise being
kept, not a fee that quietly never existed.

Strike it through, or label it "refunded". If you render `unit_price` the
invoice will appear not to add up. `subtotal` is the sum of `total`.

---

## 10. Screen: Entities (Enterprise only)

Most customers have exactly one entity and never see this. Gate the whole
section on `subscription.plan.code === "ENTERPRISE"`.

```
GET  /api/v1/teams/entities/
POST /api/v1/teams/entities/    { "legal_name": "Reed Trading LLC", "ein": "12-3456789" }
```

The **first** entity is free on any plan. The **second** requires Enterprise:

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "plan": "Multiple entities are available on the Enterprise plan only." } }
```

Note that is a **400, not a 402** — the gate is the plan tier and the message
names it.

`DELETE` **archives** (200, `status: "ARCHIVED"`). Payments reference entities,
so deleting would orphan financial history.

Enterprise includes 3 entities; each one beyond bills $79/mo and the add-on
tracks the real count automatically — archive one and the next invoice read
drops. Nobody has to tell billing.

> `GET /teams/entities/` returns `200 []` on a non-Enterprise plan, **not** an
> error. An empty array does not mean "hide the section" — gate on the plan
> code.

---

## 11. When to refetch

| After | Refetch |
|---|---|
| Login | `/teams/me/` |
| **Accepting an invitation** | `/teams/me/` — the account changed |
| Invite / remove / accept | `/teams/members/`, `/billing/allowances/` |
| Bank connect / disconnect | `/billing/allowances/` |
| Plan change | `/billing/subscription/`, `/allowances/`, `/invoice/` |
| Add-on change | `/billing/addons/`, `/invoice/` |
| Payment sent | `/billing/fees/`, `/allowances/` (checks) |
| Add-on or entity change | `/invoice/` |

---

## 12. Checklist

- [ ] `GET /teams/me/` on login; `account_id` is the cache key
- [ ] Gate UI on `capabilities`, never a hardcoded role
- [ ] 402 → upgrade dialog; 403 → "ask your admin"; both use `message` verbatim
- [ ] Render `effective_price`, not `monthly_price`
- [ ] Branch on `unlimited`, not `!limit`
- [ ] "Resets on `period_end`" only for CHECKS
- [ ] Render invoice `total`, not `unit_price`; keep refunded lines visible
- [ ] Render `email` when member `name` is `null`
- [ ] Omit `role` when re-sending an invitation
- [ ] Re-run `/teams/me/` after accepting
- [ ] Hide same-day ACH after the 11:59 PM Eastern cutoff
- [ ] Gate the entities section on `ENTERPRISE`, not on an empty array
- [ ] Branch the card form on `collects_money`, never on a build flag
- [ ] Confirm the returned `client_secret` after subscribe — skipping it
      leaves the subscription unpaid

---

## 13. Not built — do not design around these

| Gap | Impact |
|---|---|
| Dunning | A failed charge sets `PAST_DUE`, but no retry or reminder sequence runs off it yet. |
| Proration | A mid-cycle plan change takes effect immediately at the new price, with no credit. Don't promise one. |
| Invoice history | Current cycle only. No past invoices, no PDF. |
| Approval workflows / ERP sync | E10-S4, deferred by the epic. The $99 and $149 add-ons are sellable but inert. |
| Per-entity funding | Entities do not own bank connections; funding is account-wide. |
| Ownership transfer | No "make someone else the owner". |
