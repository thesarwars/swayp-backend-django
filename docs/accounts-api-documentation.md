# Account APIs Documentation

This document covers the account-related APIs under the authentication module.

Base URL:
- `/api/v1/auth/`

## Overview

These endpoints handle:
- user registration
- OTP verification
- login
- login OTP verification
- OTP resend
- token refresh and logout
- password reset flows

All of these endpoints are currently public and do not require a bearer token.

---

## 1. Register Account

### Endpoint
- `POST /api/v1/auth/register/`

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
- `POST /api/v1/auth/verify-otp/`

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
- `POST /api/v1/auth/login/`

### Purpose
Authenticate user credentials and send a login OTP.

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
  "message": "OTP has been sent."
}
```

---

## 4. Verify Login OTP

### Endpoint
- `POST /api/v1/auth/login/verify/`

### Purpose
Verify the login OTP and issue JWT tokens.

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
  "message": "Login successful.",
  "data": {
    "access": "<access_token>",
    "refresh": "<refresh_token>"
  }
}
```

---

## 5. Resend OTP

### Endpoint
- `POST /api/v1/auth/resend-otp/`

### Purpose
Resend an OTP for either registration or login.

### Request body
```json
{
  "email": "john@gmail.com",
  "purpose": "LOGIN"
}
```

### Notes
- `purpose` should be one of the supported OTP purposes such as `LOGIN` or `REGISTRATION`.

### Success response
```json
{
  "success": true,
  "message": "OTP sent successfully."
}
```

---

## 6. Refresh Access Token

### Endpoint
- `POST /api/v1/auth/refresh/`

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
- `POST /api/v1/auth/logout/`

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
- `POST /api/v1/auth/forgot-password/`

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
- `POST /api/v1/auth/reset-password/`

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
