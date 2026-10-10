# Swayp API — Frontend Integration Guide

Start here. This is the map: what the API is, the conventions that apply
everywhere, the order screens should call things in, and the traps worth
knowing before you write a line of code.

Per-domain reference lives in:

| Guide | Covers |
|---|---|
| [Banking API](banking-api-documentation.md) | bank link, scan, bill detection, import, onboarding, ABA validation |
| [Bills API](bills-api-documentation.md) | bill wizard, occurrence list, summary, invoice, QR |
| [Payments API](payments-api-documentation.md) | the pay flow, batches, cancel, failure recovery, autopay |
| [Vendors API](vendors-api-documentation.md) | payees, payment methods, lead times, directory, QR |
| [Billing API](billing-api-documentation.md) | plans, allowances, per-transaction fees, guarantee refunds, invoice |
| [Teams API](teams-api-documentation.md) | seats, roles, invitations, multi-entity accounts |
| [Bill Categories API](bill-categories-api-documentation.md) | category dropdown |

**Building screen by screen?** [**docs/frontend_api/**](frontend_api/README.md)
has one guide per epic — endpoints, build order and the traps specific to
each. Start there; the per-domain references above are the lookup layer.

Every response body in those guides was captured from the running API, not
written from a spec.

**Base URL:** `/api/v1` · **Interactive schema:** `/api/docs`

---

## 1. The five things that will bite you

Read these even if you read nothing else.

### 1.1 There are three response envelopes, not one ⚠️

The API is not yet consistent. Write one unwrap helper and use it everywhere.

| Shape | Where |
|---|---|
| `{ "success", "message", "data" }` | auth, bills, banking, categories |
| `{ "items": [...], "pagination": {...} }` | `vendors/`, `vendors/<id>/payment-methods`, `directory-search/` |
| a bare object, no wrapper | vendor create/detail/update, `vendors/qr/decode` |

Success responses in the second and third shapes have **no `success` field**;
errors always do. **Branch on the HTTP status, never on the body.**

```js
const unwrap = (body) =>
  body?.data !== undefined ? body.data :
  body?.items !== undefined ? body.items :
  body;
```

### 1.2 A Bill is a rule. A BillOccurrence is a due date.

The single most important domain idea.

A **Bill** is "WeWork, $3,200, monthly, from Aug 1". It has **no status** and is
never "paid". A **BillOccurrence** is "WeWork, $3,200, due Sep 1" — that is
what the user pays, and what carries a status.

So on the bills screen, **"Total Bills: 6"** counts bills while
**"Overdue 14 / Due 9 / Upcoming 14"** counts occurrences. Different endpoints,
numbers that do not add up to each other. That is correct.

**Build the list screen on `GET /bills/occurrences`, not `GET /bills/`.**

### 1.3 Status is computed at read time

`UPCOMING`, `DUE` and `OVERDUE` are derived from the due date on every read —
no nightly job. A bill due today reads `DUE` the moment the date rolls over;
you never need to refresh to "catch up". `SCHEDULED` and `PAID` always win over
the date.

### 1.4 Some failures are HTTP 200

**ABA routing validation** returns **200** with `success: true` and
`data.valid: false` for a bad number. The *request* succeeded; the *number*
didn't. Branch on `data.valid`.

**Bulk import** returns **201** even when it imports nothing, with a
`skipped` array explaining why. That is the idempotent no-op, not an error.

### 1.5 Money is a string, and a few fields aren't

Amounts are decimal strings (`"3200.00"`), USD. Dates are `YYYY-MM-DD`,
timestamps ISO-8601 UTC, ids UUIDs.

Exception: in **bill detail**, `overdue_amount`, `days_overdue` and
`total_paid` come back as **numbers**. Coerce.

---

## 2. Authentication

### 2.1 Registration is two steps

```
POST auth/register        →  201, OTP emailed
POST auth/verify-otp      →  account activated
```

```json
{ "first_name": "Jane", "last_name": "Smith",
  "email": "jane@acme.com", "business_name": "Acme Corporation, LLC",
  "industry": "Construction", "business_size": "11-50",
  "password": "…", "confirm_password": "…",
  "terms_accepted": true, "signatory_confirmed": true,
  "marketing_opt_in": false }
```

```json
{ "success": true, "message": "Registration successful. OTP has been sent." }
```

That is the whole payload — **no postal address, phone, billing address or
point of contact.** Onboarding Step 1 and Settings collect those. `full_name`
still works instead of the split name, so older clients are unaffected.

`account_type` defaults to `BUSINESS` ("Business accounts only" on the screen);
`INDIVIDUAL` remains valid.

> **`phone_number` is optional and validated when present.** Invented numbers
> like `+15550002222` are rejected; `+14155552671` works. **Omitting it means
> phone login is unavailable to that account permanently** — nothing can add
> one later.

Full detail: [E2 Authentication](frontend_api/e2-authentication.md).

**The account is inactive until the OTP is verified.** Logging in before that
fails.

### 2.2 Login is one step

```
POST auth/login    { "email": "…", "password": "…" }    →  200, tokens
```

There is no login OTP and no second call — `auth/login/verify` is gone and
returns 404. Skip the Enter OTP screen on the sign-in path; it belongs to
registration only.

```json
{ "success": true, "message": "OTP has been sent." }
```

```json
{ "success": true, "message": "Login successful.",
  "data": { "access": "eyJhbGciOi…", "refresh": "eyJhbGciOi…" } }
```

**The first call returns no tokens.** Don't look for them there.

Refresh tokens last **30 days** and **rotate** — `POST auth/refresh` returns a
new refresh token and invalidates the old one. Store the new one or the next
refresh fails.

Access tokens last **7 days on the development API and 15 minutes in
production**. Build the refresh loop against the 15-minute number: a client
that only works because the token outlives the session will break on the day it
ships, and the failure looks like a random logout rather than a missing
refresh.

### 2.3 Phone login

```
POST auth/login/phone/request    { "phone_number": "+14155552671" }
POST auth/login/phone/verify     { "phone_number": "…", "otp": "123456" }
```

```json
{ "success": true,
  "message": "If that number is registered, a code has been sent.",
  "data": null }
```

> **This response is identical whether or not the number exists** — deliberately,
> so the endpoint can't be used to discover who has an account. Never render
> "no account found"; you genuinely don't know. Verify returns one generic
> error for unknown number, wrong code and expired code alike.

### 2.3b Continue with Google

```
POST auth/login/google   { "id_token": "<Google ID token>", "account_type": "BUSINESS", "terms_accepted": true }
```

Sign in with Google on the device and send the **ID token**. There's no
redirect URI. The answer is the usual `{ access, refresh }` plus
`is_new_user`; on `true`, go to onboarding. An existing email is linked, not
duplicated. 503 means Google sign-in is off on this server. Details, client
IDs per platform and errors:
[E2 — Continue with Google](frontend_api/e2-authentication.md#continue-with-google).

### 2.4 OTP resend is throttled

```
POST auth/resend-otp    { "email": "…", "purpose": "LOGIN", "channel": "EMAIL" }
```

**60-second minimum gap** and **5 per hour**, per user *and* purpose.

```json
{ "success": false,
  "message": "Too many OTP requests. Try again in 59 seconds." }
```

**429 with a `Retry-After` header.** Disable the resend button for that many
seconds and show a countdown — the message already contains the number.

`purpose` is `REGISTRATION`, `LOGIN` or `RESET_PASSWORD`. `channel` accepts
`EMAIL` or `SMS`, but **`SMS` is rejected this release** — the screens exist,
the delivery doesn't. Don't offer it yet.

A throttled resend does **not** invalidate the code the user is already
holding, so "wait and use the code you have" is valid advice.

### 2.5 Password reset

```
POST auth/forgot-password   { "email": "…" }
POST auth/reset-password    { "email": "…", "otp": "…", "password": "…" }
```

**A new password cannot match the previous one** — that returns 400 with
`errors.password`. Say so before submit if you can.

A rejected reset **does not consume the OTP**, so the user can retry with a
different password using the same code.

---

## 3. What to build, in order

The API mirrors the product journey. Building in this order means each screen
has real data by the time you reach it.

```
1. Auth            register → verify → login → verify
2. Onboarding      link bank → poll scan → review → import   ← fastest path to data
3. Bills           list occurrences, detail, summary
4. Vendors         list, detail, payment methods
5. Bill wizard     vendor → category → amount → method → autopay
6. Pay             select → authorize once → poll stages → receipt
```

**Start with onboarding.** One bank link produces four vendors and four bills
with real schedules, so every downstream screen has something to render. The
alternative — hand-creating vendors and bills through the wizard — is far
slower to get to a populated UI.

Full sequence: [Banking API §2](banking-api-documentation.md).

---

## 4. The bill wizard

Five steps, and **nothing needs a `bill_id`** — the whole wizard runs before
anything is saved.

| Step | Call |
|---|---|
| 1. Vendor | `GET vendors/?search=` |
| 2. Category | `GET bill-categories/` |
| 3. Amount, frequency, first due date | none |
| 4. Payment method | `GET vendors/<id>/payment-methods?due_date=&amount=` |
| 5. Autopay + create | `POST bills/create` |

### Step 4 is the one with a trap

Pass the anchor date from step 3 as `due_date` and each method returns a
`schedule` block:

```json
"schedule": { "rail": "ACH_STANDARD", "due_date": "2026-11-30",
  "lead_business_days": 2, "initiate_by": "2026-11-25",
  "estimated_arrival": "2026-11-30", "can_meet_due_date": true }
```

**`can_meet_due_date: false` means grey the method out** — it can no longer
land in time. Weekends and US federal bank holidays are already accounted for
(the example steps over Thanksgiving).

**Omit `due_date` and `schedule` is `null` on every row**, so only send it on
this step.

### Step 5 requires consent for autopay

If the user picks **Auto-pay**, you must display authorization text, get an
explicit acceptance, and send both back verbatim:

```json
{ "autopay_mode": "AUTO",
  "autopay_consent": { "accepted": true,
    "authorization_text": "I authorize Swayp to debit my account $3,200.00 monthly for WeWork until I revoke this authorization." } }
```

- `AUTO` without it → **400, and no bill is created at all**.
- `REMIND` **must not** include a consent block → also 400. Deliberate, so a
  consent block is never silently dropped.
- `authorization_text` must be **what you actually showed**, not a template id.
  It is stored so it can be reproduced later.
- Turning autopay off revokes the authorization. Turning it back on needs a
  **fresh** block — the old one is not reused.

The create response is the review screen, with a server-built sentence safe to
render directly:

```json
{ "summary": "Swayp will pay WeWork $3,200.00 on January 1, 2027.",
  "autopay_authorized": true, "next_due_date": "2027-01-01", … }
```

---

## 5. Things that change state under you

Three operations invalidate what you have cached. Refetch after each.

| Action | Consequence |
|---|---|
| `PATCH bills/<id>/update` changing `frequency` or `anchor_date` | The schedule is **rebuilt** — unpaid future occurrences are deleted and recreated, so **occurrence ids change**. Refetch the occurrence list. |
| `DELETE bills/<id>/details` | **Soft** delete. Paid history survives, so vendor spend totals stay correct. The bill vanishes from listings. |
| `DELETE vendors/<id>` | Also soft (`status: DELETED`). Still visible under `?status=DELETED`, but `GET vendors/<id>` returns 404. |

Deleting a vendor's **primary** payment method automatically promotes another,
so `payment_rail` stays populated.

---

## 6. Errors

```json
{ "success": false, "message": "Validation failed.",
  "errors": { "<field>": ["<message>"] } }
```

| Status | Meaning |
|---|---|
| 400 | validation — read `errors` per field |
| 401 | missing or expired token → refresh, then retry |
| 402 | plan ceiling reached → **upgrade prompt**, not a permission error |
| 403 | the caller's **role** forbids it → permission message; no upgrade helps |
| 404 | not found, **or owned by another user** |
| 409 | `Idempotency-Key` reused with a different body |
| 422 | QR payload unreadable → "scan again", not a server error |
| 429 | OTP resend or routing-validation rate limit; honour `Retry-After` |

**The shape is the same everywhere:** every `errors` value is a **list of
strings** (nested objects keep their nesting, with lists at the leaves).
Every error under `/api/` is JSON, unknown routes included:
`{ "success": false, "message": "Not found." }`. An id in the URL that is
missing or not yours is **404**. An unknown id in the request body is a
**400** on that field.

**Three quirks:**

- Vendor create nests branch errors one level deeper:
  `errors.payment_method.<field>`, not `errors.<field>`.
- A resource owned by someone else returns **404, not 403** — the API does not
  confirm the id exists.
- A **402 carries `message` only, no `errors` object**, and the message is
  written to be shown to the user verbatim. Handle it globally: it surfaces
  from whichever endpoint performs the action, not from Billing.
  [Billing API §1.2](billing-api-documentation.md).

---

## 7. Working without real integrations

Providers are mocked by default, so the whole product runs with no external
accounts.

**Bank linking** — put the institution name in the public token:
`public-mock-chase`, `public-mock-bofa`, `public-mock-wellsfargo`,
`public-mock-usbank`. Every link yields the same 12-month history and the same
four detected bills. Details in [Banking API §9](banking-api-documentation.md).

**OTP delivery** — logged, not sent, in dev. Read the code from the server log
or the database.

**Directory search** returns seeded data, not a live biller directory.

---

## 8. Not built yet — do not design around these

| Gap | Impact |
|---|---|
| Real rails are not wired | Payments execute end to end against the **mock** processor. Stripe (ACH through Stripe Treasury, PRD D-1) and Lob are a config swap gated on provider enablement and the legal opinion, so the flow and every response shape are final. |
| Spend figures fill in as payments run | `total_paid` and `monthly_spend` read real payments now; they are zero only until payments exist. |
| `payee_verified` always `false` | Set by provider-run verification, which isn't wired. The trust badge will never light up yet. |
| SMS OTP | Rejected explicitly. Don't offer the channel. |
| QR payload format | Provisional. The parser reads `k=v` pairs and rejects unreadable input; expect `guessed` provenance for unfamiliar codes. |

---

## 9. Endpoint index

**Auth** — `register` · `verify-otp` · `login` · `login/google` ·
`login/phone/request/` · `login/phone/verify/` · `resend-otp/` ·
`forgot-password/` · `reset-password/` · `refresh/` · `logout/`

**Banking** — `link/token/` · `link/exchange/` · `connections/` ·
`connections/<id>/` · `accounts/` · `scans/` · `scans/<id>/` ·
`scans/<id>/candidates/` · `scans/<id>/import/` · `onboarding-summary/` ·
`routing/validate/`

**Payments** — `payments/` · `payments/<id>` · `payments/<id>/confirm` ·
`payments/<id>/status` · `payments/<id>/cancel` · `payments/<id>/failure` ·
`payments/<id>/resolve` · `payments/history` ·
`payments/batches/<id>/confirm|status|cancel/` · `webhooks/<processor>`

**Bills** — `bills/` · `bills/create` · `bills/occurrences` ·
`bills/occurrences/upcoming` · `bills/occurrences/<id>/pay` ·
`bills/summary` · `bills/next-due` · `bills/qr/decode` ·
`bills/<id>/details` · `bills/<id>/update` · `bills/<id>/payments` ·
`bills/<id>/invoice`

**Vendors** — `vendors/` · `vendors/<id>` · `vendors/summary` ·
`vendors/<id>/payment-methods` · `.../<mid>/` · `.../<mid>/set-primary/` ·
`vendors/directory-search` · `vendors/qr/decode`

**Billing** — `billing/plans` · `billing/subscription` (GET/POST/PATCH/DELETE) ·
`billing/allowances` · `billing/addons` · `billing/invoice` · `billing/fees`

**Teams** — `teams/me` · `teams/members` · `teams/members/<id>` ·
`teams/invite` · `teams/invite/accept` · `teams/entities` ·
`teams/entities/<id>`

**Categories** — `bill-categories/`

Request and response detail for each is in the per-domain guide at the top of
this document.
