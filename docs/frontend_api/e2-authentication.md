# E2 — Authentication & Accounts

Register, verify, sign in, reset a password, edit the profile, and run the
onboarding wizard.

← [Index](README.md) · Prev: [E1](e1-foundations.md) · Next: [E3 Vendors](e3-vendors.md)

**Screens:** Create Account, Choose OTP, Enter OTP, Sign In, Forgot Password,
Reset Password, Onboarding Steps 1–4.

---

## 1. Registration is two steps

```
POST auth/register/     →  201, OTP emailed
POST auth/verify-otp/   →  account activated
```

**The account is inactive until the OTP is verified.** Logging in before that
fails.

### Send exactly what the screen collects

```json
{ "first_name": "Jane", "last_name": "Smith",
  "email": "jane@acme.com",
  "business_name": "Acme Corporation, LLC",
  "industry": "Construction", "business_size": "11-50",
  "password": "…", "confirm_password": "…",
  "terms_accepted": true, "signatory_confirmed": true,
  "marketing_opt_in": false }
```

**201:**

```json
{ "success": true, "message": "Registration successful. OTP has been sent." }
```

That is the whole payload. There is **no postal address, phone, billing
address or point of contact** on this call — onboarding Step 1 and Settings
collect those, which is the right order: asking for a billing address before
the customer has chosen a plan makes no sense.

| Field | Notes |
|---|---|
| `first_name` + `last_name` | or send `full_name` instead; either works |
| `account_type` | optional, defaults to `BUSINESS` ("Business accounts only") |
| `industry`, `business_size` | free text — the dropdown option lists are not fixed server-side |
| `terms_accepted`, `signatory_confirmed` | stored **with a timestamp**; they are legal artifacts |
| `marketing_opt_in` | a preference, stored as a boolean |
| `phone_number` | optional. **Omitting it means phone login is unavailable to that account, permanently** — there is no way to add one later |

**Password rules** (all enforced): 12+ characters, one uppercase, one
lowercase, one digit, one special character.

### Verify

```
POST auth/verify-otp/    { "email": "…", "otp": "123456" }
```

---

## 2. Login is two steps too

```
POST auth/login/          →  200, OTP sent (no tokens yet)
POST auth/login/verify/   →  200, tokens
```

```json
{ "success": true, "message": "OTP has been sent." }
```

```json
{ "success": true, "message": "Login successful.",
  "data": { "access": "eyJhbGciOi…", "refresh": "eyJhbGciOi…" } }
```

**The first call returns no tokens.** Don't look for them there.

Access tokens last **15 minutes**, refresh **30 days**, and refresh tokens
**rotate** — `POST auth/refresh/` returns a new refresh token and invalidates
the old one. Store the new one or the next refresh fails.

### Phone login

```
POST auth/login/phone/request/    { "phone_number": "+14155552671" }
POST auth/login/phone/verify/     { "phone_number": "…", "otp": "123456" }
```

```json
{ "success": true,
  "message": "If that number is registered, a code has been sent.",
  "data": null }
```

> **This response is identical whether or not the number exists** — deliberately,
> so the endpoint cannot be used to discover who has an account. Never render
> "no account found"; you genuinely don't know. Verify returns one generic
> error for unknown number, wrong code and expired code alike.

Only usable by accounts that registered *with* a phone. The Create Account
screen has no phone field, so most accounts cannot use this.

---

## 3. OTP: channel choice and throttling

```
POST auth/resend-otp/    { "email": "…", "purpose": "LOGIN", "channel": "EMAIL" }
```

`purpose` is `REGISTRATION`, `LOGIN` or `RESET_PASSWORD`.

⚠️ **`channel: "SMS"` returns 501**, not a silent no-op:

```json
{ "success": false,
  "message": "SMS delivery is not available in this release. Use EMAIL." }
```

The OTP modal in the design offers "Send OTP via SMS". **Disable that option**
until SMS ships, rather than letting the user pick something that fails.

**Throttling: 60-second minimum gap, 5 per hour**, per user *and* purpose.

```json
{ "success": false,
  "message": "Too many OTP requests. Try again in 59 seconds." }
```

**429 with a `Retry-After` header.** Disable resend for that many seconds and
count down — the message already contains the number.

A throttled resend does **not** invalidate the code the user already holds, so
"wait and use the code you have" is valid advice.

---

## 4. Password reset

```
POST auth/forgot-password/   { "email": "…" }
POST auth/reset-password/    { "email": "…", "otp": "…", "password": "…" }
```

**A new password cannot match the previous one** — 400 with `errors.password`.
Say so before submit if you can; the design's helper text already does.

A rejected reset **does not consume the OTP**, so the user can retry with a
different password using the same code.

> There is no "change password while signed in". Settings has to route through
> this OTP flow.

---

## 5. Profile — the Settings screen

```
GET   /api/v1/users/profile/
PATCH /api/v1/users/profile/
```

```json
{
  "account_type": "BUSINESS",
  "email": "jane@acme.com",
  "phone_number": null,
  "is_verified": true,
  "full_name": "Jane Smith",
  "address": "",
  "billing_address": "",
  "business_name": "Acme Corporation, LLC",
  "poc_name": "Jane Smith",
  "industry": "Construction",
  "business_size": "11-50",
  "trading_name": "",
  "business_type": "",
  "website": "",
  "ein": ""
}
```

`PATCH` is partial — send only what changed. An empty body is a 400.

**Read-only:** `account_type`, `email`, `phone_number`, `is_verified`. The
first changes what the account *is*; the other two are login identifiers
verified by OTP, so changing one would be an authentication flow, not a
profile edit. Sending them is ignored, not rejected.

`business_name`, `poc_name` and the rest are **`null` on an individual
account** rather than absent, so one form renders both types without branching
on whether a key exists.

This is the screen onboarding Step 1 means by *"You can update these details
anytime in Settings"*.

---

## 6. The onboarding wizard

```
GET  /api/v1/users/onboarding/
POST /api/v1/users/onboarding/skip-bank/
```

```json
{ "total_steps": 4, "current_step": 3, "complete": false,
  "steps": [
    { "step": 1, "key": "business", "label": "Business details", "complete": true },
    { "step": 2, "key": "plan",     "label": "Choose a plan",    "complete": true },
    { "step": 3, "key": "payment",  "label": "Payment method",   "complete": false },
    { "step": 4, "key": "bank",     "label": "Connect a bank",   "complete": false,
      "skipped": false, "skippable": true }
  ] }
```

**Send the user to `current_step`.** It is `null` once nothing is outstanding.

Progress is **derived from real data**, not a stored counter, so it cannot
drift — a bank connected later from Settings completes step 4 without the
wizard being involved. Refetch after any step rather than tracking position
client-side.

⚠️ **The Figma progress bar says "Step _n_ of 5". It is wrong** — there are
four steps. Render `total_steps` from this response, never from the design.

### Skipping

Step 4 offers "Skip for now". `POST /users/onboarding/skip-bank/` records it —
this is the one thing that cannot be derived, because declining a step leaves
no trace in the data. Without it the wizard would return the user to a step
they refused on every sign-in.

A skipped step reports `skipped: true` with `complete: false`, so you can
still offer it again later.

### Which endpoint each step calls

| Step | Endpoint | Guide |
|---|---|---|
| 1 Business | `PATCH users/profile/` | this file |
| 2 Plan | `GET billing/plans/`, `POST billing/subscription/` | [E9](e9-billing.md) |
| 3 Payment | `POST billing/payment-method/setup/` | [E9](e9-billing.md) |
| 4 Bank | `POST banking/link/token/`, `link/exchange/` | [E5](e5-banking.md) |

---

## 7. On the Sign In screen — what isn't built

The design shows **Continue with Google**, **Continue with Microsoft** and
**Continue with Windows Hello**, plus an **Accountant Portal** link. None of
those exist. Email + password + OTP is the only path.

Hide them, or the first click is a dead end.
