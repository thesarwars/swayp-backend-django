# Swayp Authentication System Documentation

## Overview

The Swayp Authentication module is designed as a production-ready authentication system for a financial application. It supports secure user registration, OTP-based verification, JWT authentication, session management, password recovery, and role-based account creation.

The authentication system follows a layered architecture to separate responsibilities and keep the codebase maintainable as the application grows.

---

# Tech Stack

- Python 3.12+
- Django
- Django REST Framework
- PostgreSQL
- Simple JWT
- drf-spectacular (Swagger/OpenAPI)
- Argon2 Password Hasher
- Celery _(planned)_
- Redis _(planned)_

---

# Prerequisites

Make sure the following software is installed:

- Python 3.12+
- PostgreSQL 15+
- Git
- Virtual Environment (venv)

---

# Project Setup

## 1. Clone the Repository

```bash
git clone https://github.com/Jumatechs-Software/swayp-backend.git

cd swayp-backend
```

---

## 2. Create Virtual Environment

Linux / macOS

```bash
python -m venv venv

source venv/bin/activate
```

Windows

```powershell
python -m venv venv

venv\Scripts\activate
```

---

## 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## 4. Configure Environment Variables

Create a `.env` file in the project root.

Example:

```env
DEBUG=True

SECRET_KEY=your-secret-key

POSTGRES_DB=swayp

POSTGRES_USER=postgres

POSTGRES_PASSWORD=postgres

POSTGRES_HOST=localhost

POSTGRES_PORT=5432

ALLOWED_HOSTS=*

REDIS_URL=redis://localhost:6379
```

---

## 5. Create PostgreSQL Database

Using PostgreSQL:

```sql
CREATE DATABASE swayp;
```

---

## 6. Run Database Migrations

```bash
python manage.py makemigrations

python manage.py migrate
```

---

## 7. Native library for QR decoding (macOS/Linux)

`pyzbar` is a ctypes wrapper around the native **zbar** library and resolves
it when the QR decoder is first used.

```bash
brew install zbar                  # macOS
sudo apt-get install -y libzbar0   # Debian/Ubuntu
```

On macOS, Homebrew installs into a prefix that `ctypes.util.find_library` does
not search, so the dev server needs the prefix on its library path:

```bash
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
```

Without zbar the rest of the API still works — the import is deferred, so only
`POST /bills/qr/decode` and `POST /vendors/qr/decode` fail, with a message
naming the missing library.

---

## 8. Start Development Server

```bash
python manage.py runserver
```

The API will be available at:

```
http://127.0.0.1:8000/
```

`config/settings/local.py` (the default settings module) is written so this is
the **only** process you need:

- **Celery runs inline.** `CELERY_TASK_ALWAYS_EAGER` is on, because nothing
  consumes the queue locally. Without it a confirmed payment never leaves
  `PROCESSING` — `execute_payment` is queued, not called — and a freshly
  linked bank never finishes its transaction scan. No worker, no beat.
- **Mail goes to [mailpit](https://mailpit.axllent.org)** on `localhost:1025`,
  with the inbox at <http://localhost:8025>, rather than the SMTP host in
  `.env`. Registration OTPs land there. `brew install mailpit && brew services
  start mailpit`; set `LOCAL_REAL_EMAIL=1` to use the real host instead.
- **Postgres and Redis** are expected to be running. Both are fine as native
  services (`brew services start postgresql@18 redis`) — Docker is not needed.

---

## 9. Bank data: mock or real Plaid

`BANK_DATA_PROVIDER` decides, and `POST /banking/link/token` reports its
choice back to the client as `provider`, which is how the mobile app knows
whether to open Plaid Link or its stand-in screens.

```env
BANK_DATA_PROVIDER=mock    # canned accounts and transactions, no credentials
BANK_DATA_PROVIDER=plaid   # the real thing; needs the keys below
```

For Plaid, from the dashboard under Developers → Keys:

```env
PLAID_CLIENT_ID=...
PLAID_SECRET=...
PLAID_ENV=sandbox
PLAID_REDIRECT_URI=https://...        # registered in the dashboard; iOS/web
PLAID_ANDROID_PACKAGE_NAME=com.swayp.app   # registered too; Android
PLAID_WEBHOOK_URL=https://.../webhooks/plaid
```

Two of these are easy to get wrong:

- `PLAID_REDIRECT_URI` and `PLAID_ANDROID_PACKAGE_NAME` must be registered in
  the Plaid dashboard **and** match the mobile app's bundle id / package name,
  or an OAuth bank cannot hand the user back.
- `PLAID_WEBHOOK_URL` is registered per item at link time, not in the
  dashboard. An item linked while it is empty never reports that its history
  is ready, and that item's scan waits forever.

Production refuses to boot on `BANK_DATA_PROVIDER=plaid` with
`PLAID_ENV=sandbox`: sandbox returns invented accounts and balances, and
nothing in the UI distinguishes them from a real bank.

Sandbox linking is driven from Plaid's own `/sandbox/public_token/create` — no
UI needed — using institution `ins_109508` ("First Platypus Bank"). Note that
the item carries fourteen accounts, of which only six are depository; the
credit cards, loans and retirement accounts are deliberately not stored,
because none of them can fund an ACH debit.

---

# API Documentation

Swagger UI

```
http://127.0.0.1:8000/api/docs
```

OpenAPI Schema

```
http://127.0.0.1:8000/api/schema
```

ReDoc

```
http://127.0.0.1:8000/api/redoc
```

---

# Architecture

```
Client
   │
   ▼
API Views
   │
   ▼
Serializers
(Input Validation)
   │
   ▼
Services
(Business Logic)
   │
   ▼
Models
(Database)
```

Each layer has a single responsibility:

- **Views** handle HTTP requests and responses.
- **Serializers** validate incoming data.
- **Services** contain all business logic.
- **Models** represent database entities.

---

# Authentication Flow

## Registration

```
Client
   │
   ▼
POST /api/v1/auth/register
   │
   ▼
Validate Request
   │
   ▼
Create User
   │
   ▼
Create Profile
   │
   ▼
Create Business/Individual Profile
   │
   ▼
Generate OTP
   │
   ▼
Store Hashed OTP
   │
   ▼
Send Email/SMS
```

The account remains inactive until OTP verification succeeds.

---

## Registration Verification

```
Client
   │
   ▼
POST /api/v1/auth/verify-otp
   │
   ▼
Verify OTP
   │
   ▼
Activate User
   │
   ▼
Mark OTP Used
   │
   ▼
Generate JWT Tokens
```

---

## Login

```
Client
   │
   ▼
POST /api/v1/auth/login
   │
   ▼
Validate Email & Password
   │
   ▼
Check Lockout / Active / Verified
   │
   ▼
Generate Access Token
Generate Refresh Token
Record Session (user agent + IP)
```

---

## Forgot Password

```
Client
   │
   ▼
POST /api/v1/auth/forgot-password
   │
   ▼
Generate Reset OTP
   │
   ▼
Send Email/SMS
```

---

## Reset Password

```
Client
   │
   ▼
POST /api/v1/auth/reset-password
   │
   ▼
Verify OTP
   │
   ▼
Update Password
```

---

# Account Types

The system supports two account types.

## Individual

- Full Name
- Address
- Email
- Phone Number
- Billing Address
- Password

---

## Business

- Full Name
- Address
- Email
- Phone Number
- Business Name
- Point of Contact (POC)
- Billing Address
- Password

---

# API Endpoints

| Method | Endpoint                       | Description                 |
| ------ | ------------------------------ | --------------------------- |
| POST   | `/api/v1/auth/register`        | Register new account        |
| POST   | `/api/v1/auth/verify-otp`      | Verify the registration OTP |
| POST   | `/api/v1/auth/login`           | Login with email & password |
| POST   | `/api/v1/auth/resend-otp`      | Resend OTP                  |
| POST   | `/api/v1/auth/refresh`         | Refresh JWT tokens          |
| POST   | `/api/v1/auth/logout`          | Logout current session      |
| POST   | `/api/v1/auth/forgot-password` | Request password reset      |
| POST   | `/api/v1/auth/reset-password`  | Reset password              |

---

# Database Models

## User

Stores authentication information.

Fields:

- UUID
- Email
- Phone Number
- Password
- is_active
- is_verified
- is_staff
- failed_login_attempts
- locked_until
- created_at
- updated_at

---

## Profile

Stores common profile information.

Fields:

- User
- Account Type
- Full Name
- Address

---

## Business Profile

Stores business-specific information.

Fields:

- Business Name
- POC Name
- Billing Address

---

## Individual Profile

Stores individual-specific information.

Fields:

- Billing Address

---

## OTP

Stores OTP verification records.

Fields:

- User
- OTP Hash
- Purpose
- Expiration Time
- Used Time
- Attempts

Purposes:

- Registration
- Login
- Password Reset

---

## Refresh Token

Stores user sessions.

Fields:

- User
- Token Hash
- User Agent
- IP Address
- Expiration
- Revoked Time

---

## Audit Log

Stores security events.

Fields:

- User
- Action
- IP
- User Agent
- Metadata

---

# Security Features

The authentication system includes:

- Password hashing using Argon2
- Hashed OTP storage
- JWT authentication
- Refresh tokens
- Token blacklisting
- OTP expiration
- Session tracking
- Email normalization
- Phone number validation
- UUID primary keys
- Atomic database transactions
- API versioning
- Swagger/OpenAPI documentation

---

# Request Validation

The following validations are performed during registration:

- Unique email address
- Unique phone number
- Password confirmation
- Minimum password length
- Uppercase letter
- Lowercase letter
- Number
- Special character
- Required business fields
- Valid phone number format

---

# Project Structure

```
apps/

authentication/
├── api/
│   ├── serializers.py
│   ├── urls.py
│   └── views.py
│
├── services/
│   ├── forgot_password_service.py
│   ├── login_service.py
│   ├── login_verify_service.py
│   ├── refresh_token_service.py
│   ├── registration_service.py
│   ├── resend_otp_service.py
│   ├── reset_password_service.py
│   └── verify_otp_service.py
│
├── utils/
│   └── otp.py
│
└── models/
    ├── otp.py
    └── refresh_token.py
```

---

# Swagger Documentation

Swagger UI is available at:

```
/api/docs
```

OpenAPI schema:

```
/api/schema
```

ReDoc documentation:

```
/api/redoc
```

The Swagger interface supports:

- Interactive API testing
- JWT authorization
- Request examples
- Response schemas
- Endpoint grouping
- Authentication testing

---

# Testing Workflow

1. Register a new account.
2. Retrieve the OTP from the configured email/SMS provider (or console in development).
3. Verify the registration OTP.
4. Copy the generated JWT tokens.
5. Login with email and password — the tokens come back on that call.
6. Use the returned access token in the Swagger **Authorize** dialog.
7. Test authenticated endpoints.
8. Test refresh token rotation.
9. Test logout.
10. Test forgot password.
11. Test password reset.

---

# Future Enhancements

The current implementation provides the authentication foundation for Swayp. Future improvements may include:

- Email verification via provider integration
- SMS OTP provider integration
- Redis-backed OTP storage
- Celery background workers
- Rate limiting
- Device management
- Multi-factor authentication (MFA)
- Biometric authentication for mobile clients
- Social authentication
- KYC integration
- Login activity history
- Risk-based authentication
- Comprehensive audit dashboards
- Production monitoring and alerting

---

# Conclusion

This authentication module establishes a modular, scalable foundation for the Swayp financial platform. It separates validation, business logic, and persistence concerns while providing secure OTP-based authentication and JWT session management. The architecture is designed to support future expansion into payments, billing, expense tracking, and other financial services without requiring major changes to the authentication layer.
