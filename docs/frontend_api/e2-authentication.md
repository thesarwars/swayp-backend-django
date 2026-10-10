# E2 — Authentication & Accounts

Register, verify, sign in, reset a password, edit the profile, and run the
onboarding wizard.

← [Index](README.md) · Prev: [E1](e1-foundations.md) · Next: [E3 Vendors](e3-vendors.md)

**Screens:** Create Account, Choose OTP, Enter OTP, Sign In, Forgot Password,
Reset Password, Onboarding Steps 1–4.

> ### Changed recently — read this if you built against the old shape
>
> | What | Was | Now |
> |---|---|---|
> | **Login** | two calls: `auth/login` mailed a code, `auth/login/verify` returned tokens | **one call.** `auth/login` returns the tokens |
> | `auth/login/verify` | verified the login code | **gone — 404** |
> | `auth/verify-otp` | registration codes only | unchanged in scope, but it is now the *only* verify endpoint |
> | **Trailing slashes** | every path ended in one | **none do.** A path with a trailing slash 404s |
> | `confirm_password` | required on register and reset | **not accepted.** Match the passwords client-side |
> | Password length | 12 character minimum | **no minimum.** The character rules still apply |
>
> The Choose OTP and Enter OTP screens are still on the **registration** path.
> They are no longer on the sign-in path at all.

---

## 1. Registration is two steps

```
POST auth/register     →  201, OTP emailed
POST auth/verify-otp   →  account activated, tokens returned
```

**The account is inactive until the OTP is verified.** Logging in before that
fails.

### Send exactly what the screen collects

```json
{ "first_name": "Jane", "last_name": "Smith",
  "email": "jane@acme.com",
  "business_name": "Acme Corporation, LLC",
  "industry": "Construction", "business_size": "11-50",
  "password": "…",
  "terms_accepted": true, "signatory_confirmed": true,
  "marketing_opt_in": false }
```

**201:**

```json
{ "success": true,
  "message": "Registration successful. OTP has been sent to x***e@gmail.com.",
  "data": { "email": "x***e@gmail.com" } }
```

`data.email` is the address the code went to, masked. Render it from there
rather than parsing the sentence — every endpoint that mails a code returns it
the same way, so "check x***e@gmail.com" costs no branching.

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

**Password rules** (all enforced): one uppercase, one lowercase, one digit,
one special character. **There is no length minimum** — `Ab1@` is accepted.
`confirm_password` is not a field; compare the two boxes on the client.

### Verify

```
POST auth/verify-otp    { "email": "…", "otp": "123456" }
```

```json
{ "success": true, "message": "Account verified successfully.",
  "data": { "purpose": "REGISTRATION",
            "access": "eyJhbGciOi…", "refresh": "eyJhbGciOi…" } }
```

**Verifying signs the user in.** Tokens come back here, so the Enter OTP screen
goes straight to the dashboard — do not send them to Sign In afterwards.

`purpose` is optional on the way in and `REGISTRATION` is the only value it
accepts. Sending `LOGIN` is a 400 naming the valid choice, which is the answer
to "where did my login code go".

When there is no code to spend, the error says which case it is rather than a
flat "not found": *"No verification code is pending. Request a new one to
finish signing up"* when the account was never verified, and *"…It may have
been used already"* when it was. The second is what a double-submitted form
produces, so treat it as success-already-happened rather than an error worth
alarming about.

---

## 2. Login is one step

```
POST auth/login    { "email": "…", "password": "…" }    →  200, tokens
```

```json
{ "success": true, "message": "Login successful.",
  "data": { "access": "eyJhbGciOi…", "refresh": "eyJhbGciOi…" } }
```

**There is no login OTP and no second call.** `auth/login/verify` is gone and
returns 404. Skip the Enter OTP screen entirely on the sign-in path.

The code used to arrive in the same inbox a password reset lands in, so it was
a second step rather than a second factor. Removing it changed the number of
round trips, not who gets in: a locked, inactive or unverified account is
refused at exactly the same point it was before.

| Refusal | Response |
|---|---|
| wrong password, or no such account | 400, *"Invalid email or password."* — identical for both, deliberately |
| too many failed attempts | 400, *"Too many failed attempts. Try again in N minute(s)."* |
| registered but never verified | 400, *"Account is not verified."* → send them to Enter OTP with a resend |

Refresh tokens last **30 days** and **rotate** — `POST auth/refresh` returns a
new refresh token and invalidates the old one. Store the new one or the next
refresh fails.

Access tokens last **7 days on the development API and 15 minutes in
production**. Build the refresh loop against the 15-minute number: a client
that only works because the token outlives the session will break on the day it
ships, and the failure looks like a random logout rather than a missing
refresh.

### Phone login

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
> so the endpoint cannot be used to discover who has an account. Never render
> "no account found"; you genuinely don't know. Verify returns one generic
> error for unknown number, wrong code and expired code alike.

Only usable by accounts that have a phone number. The Create Account screen
has no phone field, so an account adds one later from Settings — see
[§5, Adding or changing the phone number](#adding-or-changing-the-phone-number).

---

## 3. OTP: channel choice and throttling

```
POST auth/resend-otp    { "email": "…", "purpose": "LOGIN", "channel": "EMAIL" }
```

`purpose` is `REGISTRATION`, `LOGIN` or `RESET_PASSWORD`.

On the web flows you want `REGISTRATION` or `RESET_PASSWORD`. **`LOGIN` codes
can only be spent at `auth/login/phone/verify`**, which needs the phone number
as well — `auth/verify-otp` refuses them, so that email login cannot be done
with an inbox instead of a password.

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

### Lifetimes and limits

| | Value | Applies to |
|---|---|---|
| Code length | 6 digits | every code |
| Lifetime | **5 minutes** from issue | every code |
| Wrong guesses | **5 per code**, then the code is dead | `verify-otp`, `reset-password`, `login/phone/verify`, `users/profile/phone/verify` |
| Gap between sends | **60 seconds** | per user and purpose |
| Sends per hour | **5** | per user and purpose |

- **A new code replaces the old one.** Requesting a code (resend, forgot
  password, phone change) deletes any unused code for the same purpose, so
  only the newest code works.
- **After 5 wrong guesses the code is refused even when it is right**, with
  400 `errors.otp: ["Too many incorrect attempts. Request a new code."]`.
  Send the user to "Send again"; there is no cooldown beyond the resend
  throttle. Phone sign-in answers with its usual generic error instead, so it
  still cannot reveal whether a number is registered.
- **`resend-otp` returns the masked address** in `data.email`, the same as
  registration and forgot-password:

  ```json
  { "success": true, "message": "OTP has been sent to x***e@gmail.com.",
    "data": { "email": "x***e@gmail.com" } }
  ```

- **`login/phone/request` is throttled on the server** with the same 60 s / 5
  per hour limits. Its answer stays neutral, so a throttled request still
  says "a code has been sent" and no new code goes out. Keep your own 60 s
  countdown on "Send again".

---

## 4. Password reset

```
POST auth/forgot-password   { "email": "…" }
POST auth/reset-password    { "email": "…", "otp": "…", "password": "…" }
```

`forgot-password` answers with the masked address, same shape as registration:

```json
{ "success": true, "message": "OTP has been sent to x***e@gmail.com.",
  "data": { "email": "x***e@gmail.com" } }
```

Same password rules as registration — character classes, no length minimum,
and **no `confirm_password`**.

**A new password cannot match the previous one** — 400 with `errors.password`.
Say so before submit if you can; the design's helper text already does.

A rejected password **does not consume the OTP**, so the user can retry with a
different password using the same code. A wrong code counts toward the
5-guess limit (§3).

Code errors are 400 with `errors.otp`: `"Invalid OTP."`, `"OTP expired.
Request a new one."`, `"Too many incorrect attempts. Request a new code."`, or
`"No reset code is pending. Request a new one."` That last one is also the
answer for an email with no account.

> There is no "change password while signed in". Settings has to route through
> this OTP flow.

---

## 5. Profile — the Settings screen

```
GET   /api/v1/users/profile
PATCH /api/v1/users/profile
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

**Read-only here:** `account_type`, `email`, `phone_number`, `is_verified`.
The first changes what the account *is*; `email` and `phone_number` are login
identifiers, so changing one is a verified flow, not a profile edit. Sending
them to `PATCH` is ignored, not rejected.

`business_name`, `poc_name` and the rest are **`null` on an individual
account** rather than absent, so one form renders both types without branching
on whether a key exists.

This is the screen onboarding Step 1 means by *"You can update these details
anytime in Settings"*.

### Adding or changing the phone number

Two calls, both signed in. The same pair adds a first number and replaces an
existing one.

```
POST /api/v1/users/profile/phone          { "phone_number": "+14155552671" }
POST /api/v1/users/profile/phone/verify   { "phone_number": "+14155552671", "otp": "123456" }
```

The first emails a code to the **account's email address**, not to the new
number. SMS is not available this release, the same reason phone sign-in
sends its codes by email. It answers with the masked address:

```json
{ "success": true, "message": "A code has been sent to x***e@gmail.com.",
  "data": { "email": "x***e@gmail.com" } }
```

The second sets the number and answers with the **updated profile**, the same
body as `GET users/profile`.

- Send the number in international format (`+1…`). It is stored as E.164.
- **The code only works for the number it was requested for.** If the user
  edits the number after requesting, request again.
- 400 with `errors.phone_number` for a number another account holds, the
  number the account already has, or an unparseable number. 400 with
  `errors.otp` for a wrong, expired or missing code.
- Throttled like any OTP (§3): 429 with `Retry-After`. To resend, call the
  first endpoint again. `auth/resend-otp` refuses `PHONE_CHANGE`, because it
  cannot know which number the code is for.

---

## 6. The onboarding wizard

```
GET  /api/v1/users/onboarding
POST /api/v1/users/onboarding/skip-bank
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

Step 4 offers "Skip for now". `POST /users/onboarding/skip-bank` records it —
this is the one thing that cannot be derived, because declining a step leaves
no trace in the data. Without it the wizard would return the user to a step
they refused on every sign-in.

A skipped step reports `skipped: true` with `complete: false`, so you can
still offer it again later.

### Which endpoint each step calls

| Step | Endpoint | Guide |
|---|---|---|
| 1 Business | `PATCH users/profile` | this file |
| 2 Plan | `GET billing/plans`, `POST billing/subscription` | [E9](e9-billing.md) |
| 3 Payment | `POST billing/payment-method/setup` | [E9](e9-billing.md) |
| 4 Bank | `POST banking/link/token`, `link/exchange/` | [E5](e5-banking.md) |

---

## 7. On the Sign In screen — what isn't built

The design shows **Continue with Google**, **Continue with Microsoft** and
**Continue with Windows Hello**, plus an **Accountant Portal** link. None of
those exist. Email + password is the only path, and phone login only for the
accounts that registered with a number.

Hide them, or the first click is a dead end.
