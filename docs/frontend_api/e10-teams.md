# E10 — Teams & Entities

Seats, roles, invitations, and multi-entity accounts.

← [Index](README.md) · Prev: [E9](e9-billing.md)

Full reference: [Teams API](../teams-api-documentation.md)

---

## 1. Call this on login, before anything else

```
GET /api/v1/teams/me
```

```json
{ "account_id": "649ac658-a529-49a6-a119-8105da9fe396",
  "is_owner": false, "role": "MEMBER",
  "capabilities": ["manage_bills", "manage_vendors", "view"] }
```

It is the one request that tells you **which account you are operating on**
and **what to render**.

```js
const me = await api('/teams/me/');
session.accountId    = me.account_id;
session.capabilities = new Set(me.capabilities);
export const can = (c) => session.capabilities.has(c);
```

⚠️ **`account_id` is your cache key, not the user id.** After accepting an
invitation a person operates on the *inviting* account; keying caches on the
user will have two teammates thrashing each other's data.

**Re-run this after accepting an invitation** — the account changes underneath
the same user.

---

## 2. Render from capabilities, never from role

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

Never write `if (role === 'ADMIN')`. The matrix can change server-side and a
hardcoded check needs a client release to catch up.

A member can **prepare** a payment but not authorize it. Only the owner
touches billing, because a plan change changes what the owner is charged.

Hiding a button is not security — the API checks every action itself. Hide it
anyway, so nobody is offered something that will fail.

## 3. 402 and 403 are different problems ⚠️

| | Means | Show | Fixed by |
|---|---|---|---|
| **402** | the plan is full | upgrade prompt | money |
| **403** | your role forbids it | "ask your admin" | nothing |

Both carry `message` only, both display verbatim.

```json
{ "success": false,
  "message": "Your Founding plan allows 3 seats. Upgrade to add more." }
```

```json
{ "success": false, "message": "Your role does not allow this action." }
```

---

## 4. Seats — the owner counts

**"Founding — 3 seats" means three people, one of whom is the owner.** A
brand-new account already reads `SEATS used 1`.

So Founding can invite **2** others. Write "you + 2 teammates", never "3
teammates".

**A pending invitation holds a seat.** The seat is taken when the invite is
*sent*, not accepted — otherwise an owner on a 3-seat plan could send thirty
invitations, all apparently fine, and the failure would land on the
thirty-first *invitee* rather than the buyer.

Seat usage is in [`GET /billing/allowances/`](e9-billing.md) and counts the
same rows the invite gate checks, so the two can never disagree.

---

## 5. Team screen

```
GET /api/v1/teams/members
```

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

The owner is always included. `REMOVED` members are not.

**`name` is `null` until accepted** — there is no user behind the address yet.
Render the email, not an empty string.

Row states to design: `ACTIVE`, `INVITED`, and `INVITED` with
`invite_expired: true` (offer "resend").

> **No invite token is returned here, by design.** It is a bearer credential
> and lives only in the invitee's inbox. There is no "copy invite link" button
> to build.

---

## 6. Invitations

```
POST /api/v1/teams/invite     { "email": "sam@example.com", "role": "ADMIN" }
```

**201.** `role` is optional and defaults to `MEMBER`. `OWNER` is not a valid
choice — an account has exactly one owner.

The address is lower-cased and trimmed, so `Sam@Example.COM ` and
`sam@example.com` are the same person.

**402** when the plan is full. Refetch allowances after a successful invite.

### Re-sending is the same call

POSTing an address that already has a **pending** invitation reissues the token
and resends the email, returning **201 with the same `id`** — one row, one
history.

⚠️ **Omit `role` when re-sending.** It then keeps the role already chosen.
Sending one changes it on purpose. (A resend does *not* silently demote a
pending admin.)

Re-inviting someone previously **removed** revives their row and takes a seat
again.

**400** when they're already on the team.

### Accepting

The emailed link points at *your* route: `FRONTEND_URL/teams/accept?token=…`.

```
POST /api/v1/teams/invite/accept     { "token": "…" }
```

**The invitee must be signed in first** — the token identifies the invitation,
not the person:

```
/teams/accept?token=X
   ↓ not signed in? → login/register, preserving ?token=X
POST /teams/invite/accept/ { token }        → 200
   ↓
re-run GET /teams/me/    ← their account_id just changed
   ↓
redirect to dashboard
```

Single use, expires after **14 days**. Every failure is a 400 with a
displayable message:

| Cause | Message |
|---|---|
| Unknown / already used | `"This invitation is not valid."` |
| Expired | `"This invitation has expired. Ask for a new one."` |
| Signed in as someone else | `"This invitation was sent to a different address."` |
| Owner downgraded meanwhile | `"This team is now full. Ask the account owner to upgrade their plan."` |

That last one is real: the owner can change plan between sending and
accepting, and the seat is re-checked at accept time.

### Role change and removal

```
PATCH  /api/v1/teams/members/<id>     { "role": "ADMIN" }
DELETE /api/v1/teams/members/<id>
```

Both **200**. DELETE sets `status: "REMOVED"` and frees the seat immediately —
history survives. The owner cannot be removed or re-roled (400).

---

## 7. What a team member actually sees

Account-owned data is shared: bills, vendors, payments, banks, the
subscription. A member opening the app sees **the account's** data, and a bill
they create belongs to the account rather than to them — otherwise their work
would vanish when they closed the tab.

**Notifications are the exception** and stay personal, because a notification
is addressed to a human.

---

## 8. Entities (Enterprise only)

Most customers have exactly one and never see this. Gate the section on
`subscription.plan.code === "ENTERPRISE"`.

```
GET    /api/v1/teams/entities
POST   /api/v1/teams/entities          { "legal_name": "…", "ein": "…" }
PATCH  /api/v1/teams/entities/<id>
DELETE /api/v1/teams/entities/<id>     ← archives
```

The **first** entity is free on any plan. The **second** requires Enterprise:

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "plan": "Multiple entities are available on the Enterprise plan only." } }
```

Note that is a **400, not a 402** — the gate is the plan *tier* and the
message names it.

⚠️ **`GET` returns `200 []` on a non-Enterprise plan**, not an error. An empty
array does not mean "hide the section" — gate on the plan code.

**DELETE archives** (200, `status: "ARCHIVED"`). Payments reference entities,
so deleting would orphan financial history.

Enterprise includes 3; each beyond bills **$79/mo**, and the add-on tracks the
real count automatically — archive one and the next invoice read drops. See
[E9](e9-billing.md).

`ein` here is a label the customer types to tell their entities apart. It is
not validated as a tax identifier and is not what the 1099 report files.

---

## 9. Order to build

1. **`GET /teams/me/` on login** — everything else depends on it.
2. **Gate the UI on `capabilities`.**
3. **Global 402 vs 403 handling.**
4. **Team screen** — list, invite, resend, change role, remove.
5. **Accept page** at `/teams/accept?token=…`, requiring login first.
6. **Seats on the billing screen**, from allowances.
7. **Entities** — Enterprise only.

---

## 10. Not built

| Gap | Note |
|---|---|
| Approval workflows | E10-S4, deferred beyond R4. The $99 add-on sells but is inert. |
| ERP sync | Same, $149. |
| Per-entity funding sources | Funding is account-wide. |
| Ownership transfer | No "make someone else the owner". |
| Accountant portal | On the Sign In design; not built. |
