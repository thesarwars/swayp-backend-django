# E2 — Authentication & Accounts

**Goal:** close the gaps between the shipped auth app and the Figma flows (channel choice, phone login, throttling, password history).
**Release:** R1 · **Blocked by:** E1-S1 (Celery for delivery) · **Screens:** 1464:15936, 1464:16992, 1464:17675, 1472:18735, 1472:18816, 1473:18911, 1473:18992, 1464:14947

> **Already shipped (do not rebuild):** register w/ account_type + business fields; purpose-scoped OTP (`OTPPurpose` = REGISTRATION/LOGIN/RESET_PASSWORD with `expires_at`, `attempts`); two-step login (`login/` → `login/verify/`); forgot/reset password; refresh/logout. Package refactor to feature files done in commit `00a6b9a`.

---

## E2-S1 · OTP delivery (email) + channel model

**As a** user **I want** my OTP delivered reliably **so that** I can verify. ⟳ **Email-only this release (BRD §1.2 — SMS deferred).** The `OTPChannel` model ships now (the SMS-OTP screen 1464:16992/1472:18816 is designed) but only the EMAIL adapter is wired; SMS stays behind a disabled flag pending the SMS-notifications decision (PRD §10-Q3).

**ORM (`apps/authentication/models/otp.py` — extend):**
```python
class OTPChannel(models.TextChoices):
    SMS = "SMS", "SMS"        # reserved — no delivery adapter this release
    EMAIL = "EMAIL", "Email"

class OTP(BaseModel):
    ...existing (user, purpose, code_hash, expires_at, attempts, used_at)...
    channel = models.CharField(max_length=10, choices=OTPChannel.choices, default=OTPChannel.EMAIL)
```
**API:** `channel` accepted but validated to EMAIL this release; delivery via Celery task `send_otp` behind a `MessagingProvider` (mock logs in dev — replaces the current `print()` in `registration_service.py`); real email adapter (Postmark/SES) wired at R4.
**AC:**
- [ ] Email OTP delivered async on register/resend/login/forgot-password paths (templated per purpose)
- [ ] `channel=SMS` rejected (422/501) while SMS is deferred — no silent no-op
- [ ] Mock provider used in tests; no real email/SMS in CI

## E2-S2 · Resend throttle

**As** the platform **I need** OTP resend rate-limiting **so that** SMS/email can't be abused.

**Work:** throttle in `ResendOTPService` (e.g. min 60s gap + max 5/hour per user+purpose, constants in settings). 429 with retry-after on violation.
**AC:**
- [ ] Unit tests for gap + hourly cap; error shape uses common exception handler

## E2-S3 · Phone-number login (request/verify pair)

**As a** user **I want** to sign in with my phone number (1464:14947 "Sign In with Phone Number") **so that** I don't need my password on mobile.

**API (feature file `user_login.py` additions):**
| Method & path | Behavior |
|---|---|
| `POST auth/login/phone/request/` | phone → user lookup → send LOGIN-purpose OTP via chosen channel (reuses existing OTP machinery) |
| `POST auth/login/phone/verify/` | phone + code → tokens (mirrors `LoginVerifyService`) |
**AC:**
- [ ] Reuses `OTPPurpose.LOGIN`; no new purpose enum
- [ ] Unknown phone returns the same shape/timing as unknown email (no user enumeration)
- [ ] Routes named `login-phone-request` / `login-phone-verify`

## E2-S4 · Password history

**As a** user resetting my password **I must not** reuse my previous password (1473:18992 helper text).

**ORM (`apps/authentication/models/password_history.py`):**
```python
class PasswordHistory(BaseModel):
    user          = FK(settings.AUTH_USER_MODEL, CASCADE, related_name="password_history")
    password_hash = models.CharField(max_length=255)
    class Meta:
        db_table = "password_history"
        ordering = ["-created_at"]
```
**Behavior:** write row on every password set (register, reset); `ResetPasswordService` rejects a new password matching the last N (=1 per design; constant) hashes.
**AC:**
- [ ] Reset with same password → validation error "must be different from previous password"
- [ ] History capped/pruned (keep last 5)

## E2-S5 · Align auth views to BaseAPIView convention *(tech debt)*

**As** maintainers **we want** auth views on `BaseAPIView`/`service_class` like every other app **so that** the layering rule has no exceptions.

**Work:** introduce an `AllowAny` variant of the base (auth endpoints are public); move per-view service wiring to `service_class`; add `selectors/` where reads exist. No behavior change.
**AC:**
- [ ] All 9+ views subclass the shared base; responses byte-identical (contract tests)

## Open items feeding this epic
- "Bill Corresponding Data" register field (PRD §10-Q5) — likely `billing_address`; confirm before adding anything.
- "Email or User ID" login (PRD §10-Q11) — **no story until the client answers** (no user-id column exists).
