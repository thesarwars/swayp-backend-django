# E2 — Account security: two-step sign-in, sessions, password

Settings → **Security**: two-step verification with an authenticator app,
"where you're signed in" with sign-out, and password changes.

← [Index](README.md) · Part of [E2 Authentication](e2-authentication.md)

Every response body here was captured from the running API. Tokens are cut
short (`eyJhbGciOi…`).

---

## 1. Every sign-in can now stop at a second step ⚠️

This changes the login screens even for users who never turn MFA on.

`POST auth/login`, `POST auth/login/google` and `POST auth/login/phone/verify`
all answer with the same five keys. **Branch on `mfa_required`, never on
whether `access` is present.**

**Without two-step verification** (unchanged, plus three keys):

```json
{ "success": true, "message": "Login successful.",
  "data": { "access": "eyJhbGciOi…", "refresh": "eyJhbGciOi…",
            "mfa_required": false, "mfa_token": null, "mfa_methods": [] } }
```

**With it on:** no tokens yet.

```json
{ "success": true, "message": "Enter the code from your authenticator app.",
  "data": { "access": null, "refresh": null,
            "mfa_required": true,
            "mfa_token": "eyJ1IjoiZDJhZjI5ZWUtZDQ1OC00NmRiLThm…:1xLjiM:V66dMoV_Wo…",
            "mfa_methods": ["totp", "recovery_code"] } }
```

Google sign-in also carries `is_new_user`; it is `false` whenever
`mfa_required` is true (a new account cannot have MFA yet).

### Finishing the sign-in

Show a **6-digit code** screen, with a **"Use a recovery code"** link that
swaps to a text field. Both go to the same endpoint:

```
POST auth/login/mfa   { "mfa_token": "…", "code": "492039" }
POST auth/login/mfa   { "mfa_token": "…", "code": "a9ae2-7tsn9" }
```

```json
{ "success": true, "message": "Login successful.",
  "data": { "access": "eyJhbGciOi…", "refresh": "eyJhbGciOi…",
            "mfa_method": "totp" } }
```

`mfa_method: "recovery_code"` means one recovery code is now spent: after
landing, nudge the user to make new ones (§3.4). The user also gets an email.

| Response | Meaning | Show |
|---|---|---|
| 400 `mfa_code_invalid` | wrong code | "That code is not valid." Clear the field, keep them on the screen |
| 400 `mfa_challenge_invalid` | `mfa_token` expired (5 min), used, or 5 wrong codes | back to the sign-in screen: "Sign in again" |
| 400 `account_locked` | 10 wrong codes across sign-ins | the message verbatim: "Too many wrong codes. Try again in 15 minutes…" |
| 429 | too many attempts from this network | honour `Retry-After` |

```json
{ "success": false, "message": "Validation failed.", "code": "mfa_code_invalid",
  "errors": { "code": ["That code is not valid. Check your authenticator app."] } }
```

```json
{ "success": false, "message": "Validation failed.", "code": "mfa_challenge_invalid",
  "errors": { "mfa_token": ["This sign-in has expired or had too many tries. Sign in again."] } }
```

- Keep `mfa_token` in memory only (not storage). It is not a session and opens
  nothing else.
- Accept spaces in the 6-digit field and send digits only. Recovery codes are
  case-insensitive and the dash is optional.
- Auto-submit on the 6th digit is fine; a code works **once**, so don't
  resubmit the same code on a retry.

---

## 2. Two-step verification settings

**Optional for every user.** All endpoints below need the signed-in user's
`Authorization: Bearer` token.

### 2.1 Status

```
GET auth/mfa
```

```json
{ "success": true, "message": "Two-step verification status.",
  "data": { "enabled": true, "enabled_at": "2026-10-27T16:07:54.537111Z",
            "recovery_codes_remaining": 10 } }
```

Off: `{ "enabled": false, "enabled_at": null, "recovery_codes_remaining": 0 }`.

Show a warning when `recovery_codes_remaining` is 3 or fewer.

### 2.2 Turning it on: three screens

**① Scan.** `POST auth/mfa/setup` (no body):

```json
{ "success": true, "message": "Scan the code with your authenticator app.",
  "data": {
    "secret": "YGP2G3ZNEXVDYJUXMB2IA2JWABOJPMHE",
    "otpauth_uri": "otpauth://totp/Swayp%3Asam%40acme.com?secret=YGP2G3ZNEXVDYJUXMB2IA2JWABOJPMHE&issuer=Swayp&algorithm=SHA1&digits=6&period=30" } }
```

- Render `otpauth_uri` as a **QR code** on the client (any QR library, e.g.
  `qrcode` on npm). The backend does not send an image.
- Under it, show `secret` in groups of four for typing in by hand ("Can't
  scan?").
- On mobile, also offer a button that opens `otpauth_uri` directly: the
  authenticator app on the same phone picks it up.
- Nothing is on yet. Calling setup again starts over with a new secret.
- 400 `mfa_already_enabled` if it is already on.

**② Confirm.** The user types the 6 digits the app shows:

```
POST auth/mfa/confirm   { "code": "492039" }
```

```json
{ "success": true, "message": "Two-step verification is on.",
  "data": { "recovery_codes": [
    "a9ae2-7tsn9", "4cqc3-md8sc", "vkdmb-vwx5c", "mknt6-vd69d", "pbejn-z8vxn",
    "8u7sb-e4ht2", "24nvm-nq2cg", "ykre8-y359b", "rx5wd-qafku", "g5nkj-x4trv" ] } }
```

A wrong code is 400 `mfa_code_invalid`; let them try again.

**③ Save recovery codes.** ⚠️ **They are shown this once and can never be
fetched again.** Give **Copy** and **Download (.txt)** buttons and an "I've
saved them" checkbox before **Done**. Each code works once, in place of an app
code, for when the phone is lost.

The user gets a "Two-step verification is on" email.

### 2.3 Turning it off

```
POST auth/mfa/disable   { "code": "492039", "password": "…" }
```

```json
{ "success": true, "message": "Two-step verification is off.", "data": null }
```

- `code` is an app code **or** a recovery code: someone who lost the phone can
  still turn it off.
- `password` is required, **except** for accounts that only use Google sign-in
  (they have none). Show the field unless the user signed up with Google.
- **Every other device is signed out**; this one stays. The user is emailed.

| Refusal | Response |
|---|---|
| wrong password | 400 `invalid_credentials`, `errors.password` |
| wrong code | 400 `mfa_code_invalid` |
| not on | 400 `mfa_not_enabled` |

### 2.4 New recovery codes

```
POST auth/mfa/recovery-codes   { "code": "492039" }
→ { "data": { "recovery_codes": [ …10 new… ] } }
```

Needs an **app** code (a recovery code is refused, so codes can't be used to
mint more). The old set stops working immediately. Show the new codes with the
same "save them now" screen as §2.2 ③.

### 2.5 Lost phone and every recovery code

Nothing in the app can help, by design. Support turns it off in the Django
admin (Authentication → MFA devices → delete the user's row). Say so on the
recovery-code screen: "Lost your phone and these codes? Contact support."

---

## 3. Where you're signed in

Each signed-in device is one **session**. It stays one session through token
refreshes until it signs out or 30 days pass without a refresh.

### 3.1 List

```
GET auth/sessions
```

```json
{ "success": true, "message": "Sessions fetched successfully.",
  "data": [
    { "id": "3cb63355-3afd-4b10-ab7d-358a67d9def6",
      "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/130.0",
      "ip_address": "203.0.113.24",
      "signed_in_at": "2026-10-27T16:07:54.524150Z",
      "last_used_at": "2026-10-27T16:07:54.522689Z",
      "expires_at": "2026-11-26T16:07:54.522689Z",
      "current": true },
    { "id": "58bf4d1c-f1ee-47f3-8381-b313069fd9dd",
      "user_agent": "Swayp/1.0 (iPhone; iOS 18.1)",
      "ip_address": "198.51.100.7",
      "signed_in_at": "2026-10-27T16:07:54.526034Z",
      "last_used_at": "2026-10-27T16:07:54.525763Z",
      "expires_at": "2026-11-26T16:07:54.525763Z",
      "current": false } ] }
```

- **`current: true` is this device.** Label it "This device" and don't offer
  "Sign out" on it (use the normal logout).
- **`user_agent` is the raw header.** Turn it into "Chrome on macOS" /
  "Swayp app on iPhone" with a UA parser (e.g. `ua-parser-js`).
- `last_used_at` is accurate to about 5 minutes: show "Active now" when it is
  within 5 minutes, otherwise relative time ("2 hours ago").
- `ip_address` can be `null`. Showing a city needs a GeoIP lookup the backend
  does not do.
- Sorted most recently used first. Ended and expired sessions are not listed.

### 3.2 Sign out one device

```
DELETE auth/sessions/<id>
→ { "success": true, "message": "Session signed out.", "data": null }
```

404 if it's not the user's or is already gone: refetch the list.

### 3.3 Sign out everywhere

```
POST auth/sessions/revoke-all   {}
→ { "data": { "revoked": 2 }, "message": "Signed out everywhere else." }
```

Signs out **every other** device; this one stays. Send
`{ "include_current": true }` to sign this device out too (then go to the
sign-in screen).

### 3.4 What happens on the device that was signed out ⚠️

It takes effect **immediately**, not when the access token would expire. The
signed-out device's next request gets:

```json
{ "success": false, "message": "This session has been signed out.",
  "code": "token_not_valid" }
```

with **401**, and its refresh attempt gets the same 401. The client already
handles `token_not_valid` by refreshing; when the **refresh** also answers
401, clear the tokens and go to the sign-in screen. Don't retry in a loop.

The WebSocket connection of a signed-out session is refused on reconnect.

### 3.5 Logout

`POST auth/logout { "refresh": "…" }` ends **this** session only. (It used to
mark every session ended; other devices stay signed in now.)

---

## 4. Password

| Feature | Endpoint | Notes |
|---|---|---|
| Change while signed in | `POST users/password` | [E2 §5](e2-authentication.md#changing-the-password-while-signed-in) |
| Forgot / reset | `POST auth/forgot-password` → `auth/verify-otp` → `auth/reset-password` | [E2 §4](e2-authentication.md#4-password-reset) |

What happens on either:

- **Every other session is signed out immediately** (§3.4). A change returns a
  fresh token pair for this device: store it.
- The previous password cannot be reused.
- **The user gets a "Your Swayp password was changed" email**, with what to do
  if it wasn't them.

Two-step verification is not asked for when changing the password; the user
is already signed in, and `current_password` is required.

---

## 5. Emails the user receives

| When | Subject |
|---|---|
| Two-step verification turned on | Two-step verification is on |
| Two-step verification turned off | Two-step verification is off |
| Signed in with a recovery code | A recovery code was used to sign in |
| Password changed or reset | Your Swayp password was changed |

No action is needed from the client; they're listed so support and the UI
copy can mention them.

---

## 6. Error codes on this page

| `code` | Status | Where |
|---|---|---|
| `mfa_code_invalid` | 400 | wrong or reused 6-digit code, or unknown recovery code |
| `mfa_challenge_invalid` | 400 | `mfa_token` expired, used, forged, or out of tries |
| `mfa_already_enabled` | 400 | setup or confirm while it's on |
| `mfa_not_enabled` | 400 | confirm before setup, disable while off |
| `account_locked` | 400 | 10 wrong sign-in codes in 15 minutes |
| `invalid_credentials` | 400 | wrong password on disable or password change |
| `token_not_valid` | 401 | session signed out, or token expired → refresh, then sign in |
| — | 429 | rate limit (20 code attempts/min per network) → `Retry-After` |

---

## 7. Order to build

1. **Sign-in screens:** handle `mfa_required` on email, Google and phone
   sign-in, plus the code / recovery-code screen. Do this first: it is the
   only part that can break existing sign-in once any user turns MFA on.
2. **401 handling:** a refresh that answers 401 sends the user to sign in.
3. **Settings → Security → Two-step verification:** status, the
   three-screen setup, turn off, new recovery codes.
4. **Settings → Security → Where you're signed in:** list, sign out one,
   sign out everywhere.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/auth/login/mfa` | none | finish a sign-in with a code |
| GET | `/api/v1/auth/mfa` | bearer | status |
| POST | `/api/v1/auth/mfa/setup` | bearer | start setup: secret + QR URI |
| POST | `/api/v1/auth/mfa/confirm` | bearer | turn on; returns recovery codes |
| POST | `/api/v1/auth/mfa/disable` | bearer | turn off |
| POST | `/api/v1/auth/mfa/recovery-codes` | bearer | replace recovery codes |
| GET | `/api/v1/auth/sessions` | bearer | where you're signed in |
| DELETE | `/api/v1/auth/sessions/<id>` | bearer | sign out one device |
| POST | `/api/v1/auth/sessions/revoke-all` | bearer | sign out everywhere else (or everywhere) |
