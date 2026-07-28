# Epics 1–4 — Completion Report

**Date:** 2026-07-28 · **Result:** 173/173 tests pass · 30/30 routes resolve · `check` and `makemigrations --check` clean.

This is what changed to close out E1–E4. Items that remain genuinely blocked are in §6 — they are blocked on E5/E6 data that does not exist yet, not skipped.

---

## 1. E2 — Authentication (was 0 of 5 stories built)

Every story in this epic was unstarted. All five now ship.

### E2-S1 · OTP channel + async delivery

Delivery was **synchronous** — a slow mail server blocked registration and login, and failures were swallowed by `print()`.

- **`OTPChannel`** (`SMS` | `EMAIL`) + a `channel` field on `OTP`.
- **New `integrations/messaging/`** — `MessagingProvider` ABC, `MockMessagingProvider` (logs, never sends), `DjangoEmailMessagingProvider` (uses `EMAIL_BACKEND`, so Postmark/SES at R4 is a settings change). Registered in the provider factory as `MESSAGING_PROVIDER`.
- **New `apps/authentication/tasks.py`** — `send_otp` Celery task with per-purpose templates. Transient failures retry with backoff; an unsupported channel does **not** retry.
- **New `OTPDeliveryService`** issues the code synchronously (so the row is guaranteed to exist) and queues delivery via `transaction.on_commit` — queuing before commit would race the worker against the OTP row.
- **`channel=SMS` is rejected**, never a silent no-op.
- `EmailService` deleted — fully superseded.

### E2-S2 · Resend throttle

Nothing existed. Now: **60s minimum gap** and **5/hour**, both per user+purpose, returning **429 with a `Retry-After` header**.

Counting `OTP` rows rather than a cache key means the limit survives a restart and cannot be dodged by hitting a different worker. The throttle runs **before** the code is regenerated, so a rejected resend does not invalidate the code the user is holding.

### E2-S3 · Phone login

Both routes 404'd. Now `POST auth/login/phone/request/` and `.../verify/`, reusing `OTPPurpose.LOGIN` — no new purpose enum.

**No user enumeration:** the request endpoint returns the same message and status whether or not the number exists, including when the account is throttled (surfacing the throttle would confirm the number). Verify returns one generic error for "no such user", "no code" and "wrong code" alike, and burns a comparable hash comparison on the unknown-user path so latency does not leak either.

### E2-S4 · Password history

New `PasswordHistory` model. Reuse is rejected against the recent hashes **and** the current password, since accounts created before this shipped have no history rows. Rejection happens **before** the OTP is consumed, so a rejected attempt does not force the user to request a fresh code. History is pruned to the last 5.

### E2-S5 · BaseAPIView alignment

All 11 auth views moved from raw `APIView` to a new **`PublicAPIView`**. It clears `authentication_classes` as well as opening permissions — leaving JWT auth on would reject a request carrying a *stale* token before the view ran, which is wrong for endpoints meant to work without one.

---

## 2. E3 — Vendors

### E3-S9 · ABA routing validation (new `apps/banking`)

`POST banking/routing/validate/` 404'd; the app did not exist. Now: mod-10 ABA checksum, prefix-range check, and a local bank-name directory.

```
021000021    valid=True   Valid – JPMorgan Chase Bank (ABA verified)
026-009-593  valid=True   Valid – Bank of America (ABA verified)   (formatting tolerated)
021000022    valid=False  Routing number failed the ABA checksum.
999000000    valid=False  Routing number does not begin with a valid ABA prefix.
```

`valid` and `bank_known` are reported **separately** — the checksum is verified arithmetic, the bank name is only as good as the local directory. A valid number missing from the directory is still valid.

The routing number is **write-only and never echoed back**, masked input is rejected, and the endpoint is rate-limited at 30/min.

### E3-S4 · Vendor spend history

`GET vendors/<id>/` now returns `total_paid`, a dense **12-bucket** `monthly_spend` series, and `next_bill`. Zero-filling is done in Python so quiet months still appear rather than collapsing the chart.

### `summary.check_total` — was hardcoded `0`

Now the summed per-cycle amount of every bill routed over CHECK, excluding soft-deleted bills.

### Bug · Deleting the primary payment method left no primary

A vendor kept its other methods but `payment_rail` went `null` and the rail chip vanished. Deleting a primary now promotes the oldest remaining method.

### Bug · `POST /vendors/` 500'd

`TypeError: create() got multiple values for keyword argument 'is_primary'` whenever the client sent `is_primary`. Also removed a shadowed duplicate `VendorPaymentMethodService`.

---

## 3. E4 — Bills

### E4-S2 · Occurrence-backed list

`GET bills/` returned bill *rules*. New **`GET bills/occurrences/`** returns the rows the screen actually shows — vendor + logo, due date, status chip, amount — paginated, with `status`, `vendor`, `date_from`, `date_to` filters.

`status` filters on the **computed** annotation, so "overdue" means what the screen shows rather than what happens to be stored.

### E4-S4 · Payment history

Added **`Payment.bill_occurrence`** (nullable FK, `SET_NULL`) — the link E4-S1 specifies and E6-S1 was expected to bring. It unblocks both this story and E3-S4.

`GET bills/<id>/payments/` joins Payment through the occurrence, so a retry — a second Payment against the same occurrence — appears as its own row.

### E4-S7 · QR + invoice

- **`POST bills/qr/decode/`** delegates to the vendor parser. The AC is "shared parser, one code path"; this adds bill-shaped coercion (amount → Decimal, due → date) on top of one decode implementation. A value that will not coerce loses its `detected` provenance flag rather than being reported as read.
- **`GET bills/<id>/invoice/`** renders from bill fields only (no OCR in v1), including the payment reference and a `qr_payload` in the same `k=v` shape the shared parser reads — so a Swayp invoice scans straight back into the wizard. There is a test that round-trips it.

---

## 4. E1 — Foundations

### E1-S5 · Date-engine tests

The engine was correct but untested beyond recurrence. Added table-driven coverage for the AC's named cases: Fri+1=Mon, holiday skip, month-end clamps, DST boundaries, plus Fed observance rules (a Sunday holiday shifts to Monday; a Saturday one does **not** shift to Friday) and a property check that initiation never lands on a non-business day across 60 consecutive due dates and all four rails.

---

## 5. Cross-cutting

| Change | Why |
|---|---|
| **`apps/__init__.py` added** | `apps/` was a namespace package, so `manage.py test` discovered **0 tests** repo-wide. Every stub had never run. |
| **9 stub `tests.py` removed** | Empty Django stubs shadowed the new `tests/` packages and broke discovery. |
| **Error messages no longer leak DRF internals** | A `ValidationError({"detail": ...})` rendered as `"[ErrorDetail(string='Account is inactive.', code='invalid')]"`. Affected the existing login endpoint too. |
| **`Retry-After` survives the error handler** | The handler rebuilds the response body, which dropped the header. |

---

## 6. Still blocked — and why

These are **not** skipped; they need data that does not exist until later epics.

| Item | Blocked on |
|---|---|
| `monthly_spend` / `total_paid` return zeros | Real `Payment` rows. The query and shape are correct and tested; nothing has paid anything yet. |
| Vendor `payee_verified` always `false` | Provider-run account verification (BRD §3.3) — E5. |
| Directory search is mock-backed | PRD §10-Q1 — how Swayp discovers Stripe configured-account vendors. |
| QR payload format is provisional | PRD §10-Q6. The parser accepts `k=v` and rejects unreadable input; the real spec is open. |

### Two decisions worth a second look

1. **`REMIND` sent with an `autopay_consent` block is rejected (400)**, not ignored. The epic only says REMIND creates no authorization. Silently discarding it is the pattern behind several bugs already fixed here — but it is stricter than the letter of the AC.
2. **`NETWORK` has lead 0 but transit 1** in `RAIL_LEAD/TRANSIT_BUSINESS_DAYS`, so a network payment initiated on its due date is estimated to arrive a day late. Every other rail has lead == transit. E1-S5 marks exact SLAs product-tunable, so it was left alone — but the asymmetry looks unintended.

---

## 7. New endpoints

| Method | Path | Story |
|---|---|---|
| `POST` | `/api/v1/auth/login/phone/request/` | E2-S3 |
| `POST` | `/api/v1/auth/login/phone/verify/` | E2-S3 |
| `POST` | `/api/v1/banking/routing/validate/` | E3-S9 |
| `GET` | `/api/v1/bills/occurrences/` | E4-S2 |
| `GET` | `/api/v1/bills/<id>/payments/` | E4-S4 |
| `GET` | `/api/v1/bills/<id>/invoice/` | E4-S7 |
| `POST` | `/api/v1/bills/qr/decode/` | E4-S7 |

Extended: `GET vendors/<id>/` (spend panel), `GET vendors/summary/` (real `check_total`), `POST auth/resend-otp/` (`channel`, 429).

---

## 8. Migrations

| App | Migration |
|---|---|
| `authentication` | `0002_otp_channel_passwordhistory` |
| `payments` | `0004_payment_bill_occurrence_and_more` |

`apps/banking` has no models — validation is pure computation over a local directory.

---

## 9. Verification

```
manage.py test          173 tests, OK
manage.py check         no issues
makemigrations --check  no changes detected
routes                  30/30 resolve
```

Test counts by area: 33 date engine · 31 auth · 33 banking + bills QR/invoice/list · 25 vendors · 51 bills occurrence/consent/edit-delete/recurrence.
