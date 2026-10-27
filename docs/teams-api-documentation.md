# Teams API Documentation

Team members, seats, roles, invitations, and multi-entity accounts.

**Base URL:** `/api/v1/teams`
**Auth:** every endpoint requires `Authorization: Bearer <access_token>`.

Every response body below was captured from the running API.

Related: [Billing API](billing-api-documentation.md) · [Payments API](payments-api-documentation.md) · [Frontend Guide](frontend-integration-guide.md)

---

## 1. Read this first

### 1.1 The owner occupies a seat ⚠️

**"Founding — 3 seats" means three people, one of whom is the owner.** A
brand-new account already shows `SEATS used 1` before anyone is invited.

So a Founding account can invite **2** others, not 3. Say "2 seats left", not
"3 seats" — the pricing page number is total headcount.

### 1.2 A pending invitation holds a seat

The seat is taken when the invite is *sent*, not when it is accepted. Otherwise
an owner on a 3-seat plan could send thirty invitations, all apparently fine,
and the failure would land on the thirty-first person trying to accept —
in front of the wrong human entirely.

Practically: an `INVITED` row counts in `SEATS.used`, and withdrawing an
invitation frees the seat immediately.

### 1.3 402 is a seat limit, 403 is a role ⚠️

Two different refusals that are easy to conflate:

| Status | Means | Show |
|---|---|---|
| **402** | the plan is full | an **upgrade prompt** — money fixes it |
| **403** | this role may not do this | a **permission message** — no upgrade helps |

Sending a 403 to the pricing page is a dead end for the user. Sending a 402 to
"ask your admin" hides a sale. Both carry `message` only, with no `errors`
object, and both messages are written to be displayed verbatim.

### 1.4 An invited member acts on the inviting account ⚠️

After accepting, a user's requests operate on the **owner's** account, not a
private one of their own. `GET /teams/me` returns that `account_id`.

This is not just a label — it is what the data is keyed on. A member calling
`GET /bills/occurrences`, `/vendors`, `/banking/accounts`,
`/dashboard/home`, `/payments/history` or `/billing/subscription` sees the
**account's** rows, and a bill they create belongs to the account rather than
to them. Otherwise their work would vanish the moment they closed the tab.

**Personal things stay personal.** Notifications are addressed to a human,
not an account, and so is everything under `auth`. Those still scope to the
signed-in user.

### 1.5 Everyone is solo until they invite someone

An account with no team behaves exactly as it did before Teams existed: the
owner holds every capability and nothing is gated. Nothing here changes
single-user behaviour.

---

## 2. Roles

Five roles, fixed. The split is deliberate: **an Accountant prepares work, an
Approver moves money, and only the owner changes what the owner is charged.**

| Capability | OWNER | ADMIN | APPROVER | MEMBER (Accountant) | VIEWER |
|---|:---:|:---:|:---:|:---:|:---:|
| `view` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `manage_bills` — bills, scans, mark paid | ✅ | ✅ | ✅ | ✅ | — |
| `manage_vendors` — add, edit, delete, restore | ✅ | ✅ | ✅ | ✅ | — |
| `schedule_payments` — create, edit, cancel, resolve | ✅ | ✅ | ✅ | ✅ | — |
| `send_money` — confirm payments, turn autopay on | ✅ | ✅ | ✅ | — | — |
| `manage_vendor_payment_details` — an existing vendor's payment methods | ✅ | ✅ | — | — | — |
| `manage_banks` — link, disconnect, default funding account | ✅ | ✅ | — | — | — |
| `manage_team` | ✅ | ✅ | — | — | — |
| `manage_entities` | ✅ | ✅ | — | — | — |
| `manage_billing` — plan, add-ons, card | ✅ | — | — | — | — |
| `manage_account` — `PATCH /users/profile` | ✅ | — | — | — | — |

`MEMBER` is shown as **Accountant**: the stored value stayed `MEMBER` so
existing seats kept their role. Label roles in the UI as Owner, Admin,
Approver, Accountant, Viewer.

- **An Accountant prepares, an Approver sends.** A payment an Accountant
  schedules waits for `confirm` from someone with `send_money`.
- **Autopay counts as approving.** A bill request that sets `autopay_mode:
  AUTO` or carries `autopay_consent` needs `send_money`; turning autopay off
  needs only `manage_bills`.
- **Adding a vendor is not repointing one.** `POST /vendors` (with its first
  payment method) is `manage_vendors`; anything under
  `/vendors/<id>/payment-methods` is `manage_vendor_payment_details`, because
  redirecting a known payee's money is the classic payment fraud.
- **Owner-only:** billing, and the account profile (business name, billing
  address). Every role can read both.

A refusal for the role is **403** with `code: "role_forbidden"` and the
missing `capability`:

```json
{ "success": false, "message": "Your role does not allow this action.",
  "code": "role_forbidden", "capability": "send_money" }
```

**Read capabilities from the API, do not hardcode this table.** Every member
object and `GET /teams/me` carries a `capabilities` array; render off that and
a future role change needs no client release.

Hiding a button is not enforcement — the API checks every action itself.

---

## 3. Who am I?

```
GET /api/v1/teams/me
```

**Call this on login.** It is the one request that tells you which account you
are operating on and what to render.

**200:**

```json
{
  "success": true,
  "message": "Role fetched successfully.",
  "data": {
    "account_id": "649ac658-a529-49a6-a119-8105da9fe396",
    "is_owner": true,
    "role": "OWNER",
    "capabilities": [
      "manage_banks", "manage_billing", "manage_bills", "manage_entities",
      "manage_team", "manage_vendors", "send_money", "view"
    ]
  }
}
```

A member sees the same shape with less in it:

```json
{ "account_id": "649ac658-…", "is_owner": false, "role": "MEMBER",
  "capabilities": ["manage_bills", "manage_vendors", "view"] }
```

---

## 4. Team members

```
GET /api/v1/teams/members
```

**200** — the owner is always included:

```json
{
  "success": true,
  "message": "Team members fetched successfully.",
  "data": [
    {
      "id": "a3a60e69-f2e0-4343-928d-b357123e98d9",
      "email": "owner@example.com",
      "name": "Dana Reed",
      "role": "OWNER",
      "status": "ACTIVE",
      "capabilities": ["manage_banks", "manage_billing", "…"],
      "invite_expired": false,
      "invite_expires_at": null,
      "accepted_at": "2026-07-29T09:50:44.372859Z",
      "created_at": "2026-07-29T09:50:44.373859Z"
    },
    {
      "id": "4174b528-6931-4a6f-ab60-6b6b86d28158",
      "email": "lee@example.com",
      "name": null,
      "role": "MEMBER",
      "status": "INVITED",
      "capabilities": ["manage_bills", "manage_vendors", "view"],
      "invite_expired": false,
      "invite_expires_at": "2026-08-12T09:50:44.747249Z",
      "accepted_at": null,
      "created_at": "2026-07-29T09:50:44.747249Z"
    }
  ]
}
```

`name` is `null` until the invitation is accepted — there is no user behind the
address yet. **Render `email` when `name` is null**, not an empty string.

`REMOVED` members are excluded from this list.

**The invite token is never returned here.** It is a bearer credential and
lives only in the invitee's inbox. Do not build a "copy invite link" button
against this endpoint; there is nothing to copy.

---

## 5. Invitations

### 5.1 Send

```
POST /api/v1/teams/invite
```

```json
{ "email": "sam@example.com", "role": "ADMIN" }
```

`role` is one of `ADMIN`, `APPROVER`, `MEMBER` (Accountant) or `VIEWER`; it
is optional and defaults to `MEMBER`. `OWNER` is not a valid choice — an
account has exactly one owner. The same four are valid for a role change.

**201:**

```json
{
  "success": true,
  "message": "Invitation sent.",
  "data": {
    "id": "17b21309-6eb9-46a6-80c5-a705c7448190",
    "email": "sam@example.com",
    "name": null,
    "role": "ADMIN",
    "status": "INVITED",
    "capabilities": ["manage_banks", "manage_bills", "…"],
    "invite_expired": false,
    "invite_expires_at": "2026-08-12T09:50:44.461268Z",
    "accepted_at": null,
    "created_at": "2026-07-29T09:50:44.461268Z"
  }
}
```

The email address is lower-cased and trimmed, so `Sam@Example.COM ` and
`sam@example.com` are the same person.

**402 — the plan is full:**

```json
{ "success": false,
  "message": "Your Founding plan allows 3 seats. Upgrade to add more." }
```

### 5.2 Re-sending is the same call

POSTing an address that already has a **pending** invitation reissues the token
and resends the email. It returns **201 with the same `id`** — one row, one
history, not a duplicate.

**Omit `role` when re-sending.** It then keeps whatever role was already
chosen; passing one changes it on purpose. (Sending no role does *not* silently
demote a pending admin to member.)

Re-inviting someone previously **removed** revives their row and takes a seat
again.

**400 — already on the team:**

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "email": ["This person is already on your team."] } }
```

### 5.3 Accept

```
POST /api/v1/teams/invite/accept
```

```json
{ "token": "…from the emailed link…" }
```

The invitee must be **signed in** — the token identifies the invitation, not
the person. The link in the email points at your frontend
(`FRONTEND_URL/teams/accept?token=…`); send them through login first, then call
this.

**200** — `status` becomes `ACTIVE` and `name` fills in.

The token is **single-use** and expires after **14 days**. Every failure is a
400 with a message safe to display:

| Cause | Message |
|---|---|
| Unknown or already-used token | `"This invitation is not valid."` |
| Already accepted | `"This invitation has already been accepted."` |
| Withdrawn | `"This invitation was withdrawn."` |
| Past 14 days | `"This invitation has expired. Ask for a new one."` |
| Signed in as someone else | `"This invitation was sent to a different address."` |
| Owner downgraded meanwhile | `"This team is now full. Ask the account owner to upgrade their plan."` |

That last one is worth handling properly: the owner can change plan between
sending an invitation and its acceptance, and the seat is re-checked at accept
time rather than honoured blindly.

### 5.4 Change a role, or remove someone

```
PATCH  /api/v1/teams/members/<member_id>     { "role": "APPROVER" }
DELETE /api/v1/teams/members/<member_id>
```

Both return **200** with the member. DELETE sets `status: "REMOVED"` rather
than deleting — the seat frees immediately and the history survives.

The owner cannot be removed and their role cannot be changed; both are 400.

---

## 6. Seats and billing

Seats are a plan allowance, so they appear in the Billing API:

```
GET /api/v1/billing/allowances
```

```json
"SEATS": { "limit": 3, "unlimited": false, "used": 2, "remaining": 1 }
```

`used` is counted from the team members themselves, so **this number and the
402 always agree** — when `remaining` is 0, the invite button genuinely will
refuse, and removing someone frees it on the next read.

| Plan | Seats (including the owner) |
|---|---|
| Founding | 3 |
| Standard | 10 |
| Enterprise | unlimited (`limit: null`) |

`limit: null` means unlimited, not zero — see
[Billing API §1.4](billing-api-documentation.md).

**Refetch allowances after any invite, accept or removal.**

---

## 7. Entities (multi-entity accounts)

An entity is a legal business under one Swayp account. Most customers have
exactly one and never see this feature.

### 7.1 The first is free; the second needs Enterprise

```
GET  /api/v1/teams/entities
POST /api/v1/teams/entities
```

```json
{ "legal_name": "Reed Trading LLC", "ein": "12-3456789" }
```

**201:**

```json
{
  "success": true,
  "message": "Entity created.",
  "data": {
    "id": "679315f6-087c-430d-82a1-1f2b8b504d22",
    "legal_name": "Reed Trading LLC",
    "ein": "12-3456789",
    "status": "ACTIVE",
    "created_at": "2026-07-29T09:50:44.861110Z"
  }
}
```

**400 — a second entity on a non-Enterprise plan:**

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "plan": ["Multiple entities are available on the Enterprise plan only."] } }
```

Note this is a **400, not a 402** — the gate is the plan *tier*, and the
message names it. Duplicate `legal_name` on one account is also a 400.

`ein` is a label the customer types to tell their own entities apart. It is not
validated as a tax identifier and is not what E8's 1099 reporting files.

### 7.2 Archiving, not deleting

```
DELETE /api/v1/teams/entities/<entity_id>
```

Returns **200** with `status: "ARCHIVED"`. Bills and payments reference
entities, so deleting one would either take financial history with it or orphan
it. Archived entities drop out of `GET /entities` and stop counting for
billing.

### 7.3 Entities beyond three bill $79/mo

Enterprise includes 3. The extra-entity add-on tracks the real count
automatically — nobody has to tell billing:

```json
{ "kind": "EXTRA_ENTITY", "description": "Extra entity",
  "quantity": 1, "unit_price": "79.00", "total": "79.00" }
```

With 4 active entities, `quantity` is 1. Archive one and it drops to 0 on the
next invoice read. See [Billing API §9](billing-api-documentation.md).

### 7.4 Scoping

Bills, vendors and payments carry a nullable `entity`. **A single-entity
account leaves it null and behaves exactly as before** — that is what makes
this safe on existing data.

When an account has exactly one entity it is used automatically. With several,
the entity must be stated explicitly: guessing would file a bill against the
wrong company.

---

## 8. What to build, in order

1. **`GET /teams/me` on login** — store `account_id`, `role`, `capabilities`.
2. **Gate the UI on `capabilities`**, never on a hardcoded role check.
3. **Global 402 vs 403 handling** — upgrade prompt vs permission message.
4. **Team screen** — `GET /members`, invite, resend, change role, remove.
5. **Accept page** — a frontend route at `/teams/accept?token=…` that requires
   login and then POSTs the token.
6. **Seats on the billing screen** — from `GET /billing/allowances`.
7. **Entities** — Enterprise only; hide the section otherwise.

---

## 9. Not built yet — do not design around these

| Gap | Impact |
|---|---|
| Approval workflows | E10-S4, explicitly deferred beyond R4 in the epic. No approval step gates payment confirm. The $99 add-on is sellable but inert. |
| ERP sync | E10-S4, same. The $149 add-on is sellable but inert. |
| Per-entity funding sources | An entity does not yet own its own bank connections; funding is account-wide. |
| Ownership transfer | There is no "make someone else the owner". The owner is the account. |

---

## 10. Endpoint index

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/teams/me` | caller's account, role and capabilities |
| GET | `/api/v1/teams/members` | everyone on the account |
| POST | `/api/v1/teams/invite` | invite, or re-send |
| POST | `/api/v1/teams/invite/accept` | accept an invitation |
| PATCH | `/api/v1/teams/members/<id>` | change a role |
| DELETE | `/api/v1/teams/members/<id>` | remove a member, freeing the seat |
| GET | `/api/v1/teams/entities` | active entities |
| POST | `/api/v1/teams/entities` | create an entity |
| PATCH | `/api/v1/teams/entities/<id>` | rename, or set the EIN |
| DELETE | `/api/v1/teams/entities/<id>` | archive |
