# Account APIs Documentation

This document covers the account-related APIs under the authentication module.

Base URL:
- `/api/v1/auth`

## Overview

These endpoints handle:
- user registration
- OTP verification
- login
- login (one step — no OTP)
- phone-number login
- OTP resend (rate limited)
- token refresh and logout
- password reset flows

All of these endpoints are public and do not require a bearer token.

> New in E2, and easy to miss: OTP resend is **rate limited** (§5), phone login
> exists (§5b), and a password reset **cannot reuse the previous password**
> (§8). See the [Frontend Integration Guide](frontend-integration-guide.md) §2
> for the whole auth flow in one place.

---

## 1. Register Account

### Endpoint
- `POST /api/v1/auth/register`

### Purpose
Create a new user account.

### Request body
```json
{
  "account_type": "BUSINESS",
  "full_name": "John Doe",
  "address": "Dhaka",
  "email": "john@gmail.com",
  "phone_number": "+8801712345678",
  "password": "Password@123",
  "confirm_password": "Password@123",
  "business_name": "ABC Ltd",
  "poc_name": "John Doe",
  "billing_address": "Dhaka"
}
```

### Notes
- `account_type` can be `BUSINESS` or another supported type from the system.
- For business accounts, `business_name` and `poc_name` are required.
- Password must be at least 12 characters and include uppercase, lowercase, number, and special character.
- `phone_number` is validated properly. Invented numbers such as
  `+15550002222` are rejected; use real-format numbers in fixtures.
- The account is **inactive until the OTP is verified** — logging in before
  that fails.

### Success response
```json
{
  "success": true,
  "message": "Registration successful. OTP has been sent."
}
```

---

## 2. Verify Registration OTP

### Endpoint
- `POST /api/v1/auth/verify-otp`

### Purpose
Verify the OTP sent after account registration.

### Request body
```json
{
  "email": "john@gmail.com",
  "otp": "123456"
}
```

### Success response
```json
{
  "success": true,
  "message": "Account verified successfully.",
  "data": {
    "access": "<access_token>",
    "refresh": "<refresh_token>"
  }
}
```

---

## 3. Login

### Endpoint
- `POST /api/v1/auth/login`

### Purpose
Authenticate credentials and issue JWT tokens. One step: there is no login
OTP. The code used to arrive in the same inbox a password reset lands in, so
it was a second step rather than a second factor.

### Request body
```json
{
  "email": "john@gmail.com",
  "password": "Password@123"
}
```

### Success response
```json
{
  "success": true,
  "message": "Login successful.",
  "data": {
    "access": "<access_token>",
    "refresh": "<refresh_token>"
  }
}
```

### Refusals
A locked, inactive or unverified account is refused at the same point it was
before — removing the OTP changed the number of round trips, not who gets in.

---

## 4. Verify Login OTP — removed

`POST /api/v1/auth/login/verify` no longer exists and returns 404. Login
returns its tokens directly (§3).

`POST /api/v1/auth/verify-otp` finishes a **registration** and nothing else.
It refuses a `LOGIN` code deliberately: `resend-otp` will mail one to any
registered address, so a verify that spent it would hand out tokens for
possession of the inbox and make the password optional again. Login codes
still exist for the phone flow and are spent at
`POST /api/v1/auth/login/phone/verify`, which needs the phone number too.

---

## 5. Resend OTP

### Endpoint
- `POST /api/v1/auth/resend-otp`

### Purpose
Resend an OTP for either registration or login.

### Request body
```json
{
  "email": "john@gmail.com",
  "purpose": "LOGIN",
  "channel": "EMAIL"
}
```

### Notes
- `purpose` is `REGISTRATION`, `LOGIN` or `RESET_PASSWORD`.
- `channel` is optional and defaults to `EMAIL`. `SMS` is **rejected** this
  release — the screens exist but no delivery adapter is wired, so do not
  offer it.

### Success response
```json
{
  "success": true,
  "message": "OTP sent successfully."
}
```

### Rate limit — 429

Resend is throttled per user **and** purpose: a **60-second minimum gap** and
**5 per hour**.

```json
{
  "success": false,
  "message": "Too many OTP requests. Try again in 59 seconds."
}
```

The response carries a **`Retry-After`** header with the same number of
seconds. Disable the resend button and count down.

A throttled resend does **not** invalidate the code the user already holds, so
"wait and use the code you have" remains valid.

---

## 5b. Phone-Number Login

### Endpoints
- `POST /api/v1/auth/login/phone/request`
- `POST /api/v1/auth/login/phone/verify`

### Purpose
Sign in with a phone number instead of a password.

### Request — step 1
```json
{
  "phone_number": "+14155552671"
}
```

### Success response
```json
{
  "success": true,
  "message": "If that number is registered, a code has been sent.",
  "data": null
}
```

> This response is **identical whether or not the number is registered**, by
> design, so the endpoint cannot be used to discover who has an account. Never
> render "no account found" — you genuinely do not know.

### Request — step 2
```json
{
  "phone_number": "+14155552671",
  "otp": "123456"
}
```

Returns the same `{ access, refresh }` pair as §4. Verify returns one generic
error for unknown number, wrong code and expired code alike.

---

## 6. Refresh Access Token

### Endpoint
- `POST /api/v1/auth/refresh`

### Purpose
Generate a new access token using a refresh token.

### Request body
```json
{
  "refresh": "<refresh_token>"
}
```

### Success response
```json
{
  "success": true,
  "data": {
    "access": "<new_access_token>",
    "refresh": "<refresh_token>"
  }
}
```

---

## 7. Logout

### Endpoint
- `POST /api/v1/auth/logout`

### Purpose
Logout the current session by invalidating the refresh token.

### Request body
```json
{
  "refresh": "<refresh_token>"
}
```

### Success response
- Status: `204 No Content`

---

## 8. Forgot Password

### Endpoint
- `POST /api/v1/auth/forgot-password`

### Purpose
Send a password reset OTP to the user email.

### Request body
```json
{
  "email": "john@gmail.com"
}
```

### Success response
```json
{
  "success": true,
  "message": "OTP sent successfully."
}
```

---

## 9. Reset Password

### Endpoint
- `POST /api/v1/auth/reset-password`

### Purpose
Reset the user password using the OTP received via email.

### Request body
```json
{
  "email": "john@gmail.com",
  "otp": "123456",
  "password": "NewPassword@123",
  "confirm_password": "NewPassword@123"
}
```

### Success response
```json
{
  "success": true,
  "message": "Password reset successful."
}
```

### Password reuse is rejected

A new password cannot match the previous one:

```json
{
  "success": false,
  "message": "Validation failed.",
  "errors": {
    "password": ["New password must be different from your previous password."]
  }
}
```

A rejected reset **does not consume the OTP**, so the user can retry with a
different password using the same code.

---

## Common Validation Errors

Typical error responses include:
- invalid email/password
- invalid OTP
- expired OTP
- passwords do not match
- account is inactive or not verified
- user not found

These errors are returned as validation errors with a message in the response body.
