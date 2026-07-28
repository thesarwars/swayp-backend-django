# Pending Changes — E1–E4 Audit

**Audited:** 2026-07-28 · **Scope:** epics 1–4 against the code on `epic3/vendor-defect-fixes`.

Everything below is a change I want to make but have **not** made. Items already fixed are listed at the bottom for context only.

Legend — **Broken:** built, but wrong. **Missing:** never built. **Debt:** works, but off-convention.

---

## P0 — ✅ Done

Items 1–3 are shipped; see the commit table at the bottom.

1. ~~`payment-methods/?due_date=&amount=` ignored its params~~ — `43dc119`
2. ~~Editing a bill did not regenerate occurrences~~ — `4915885`
3. ~~Deleting a bill destroyed paid history~~ — `4915885`

**E4-S3 is unblocked.** The wizard method step now has a schedule to render.

---

## P1 — E4 remaining stories

### 4. Autopay consent capture
**Missing · E4-S3 / E4-S5**

`StandingAuthorization` exists and has a table (Phase 0) but nothing ever writes to it.

- Add `autopay_consent` (bool + shown text) to the create/update serializers.
- `autopay_mode=AUTO` without consent → **400**; `REMIND` writes no authorization.
- New `ConsentService`: persist `authorization_text`, `accepted_at`, `ip`, `user_agent`.
- Toggling AUTO off sets `revoked_at`; toggling back on captures a fresh row.

> NACHA: a beat job cannot mint consent. It must be captured in the request that enables AUTO.

### 5. Bill list is bill-backed, not occurrence-backed
**Broken · E4-S2 · [apps/bills/views/bill.py](../apps/bills/views/bill.py), [apps/bills/selectors/bill_selector.py](../apps/bills/selectors/bill_selector.py)**

`GET bills/` returns `Bill` rows. The epic's core decision is that every screen shows **occurrences**. Needs occurrence-backed rows (vendor + logo, due date, status chip, amount), filters `status|vendor|date_from|date_to`, and pagination via the annotation from [occurrence_status.py](../apps/bills/selectors/occurrence_status.py).

### 6. Review-summary echo on create
**Missing · E4-S3** — response should echo *"Swayp will pay WeWork $3,200 on Jan 1…"*.

### 7. `GET bills/<id>/payments/`
**Missing · E4-S4** — needs a `bill_occurrence` FK on [Payment](../apps/payments/models/payment.py), which doesn't exist. **Blocked on E6-S1.** Until then history can only read the occurrence's own `payment_reference`.

### 8. Days-overdue should use the date engine
**Debt · E4-S4 · [apps/bills/serializers/bill_detail_serializer.py](../apps/bills/serializers/bill_detail_serializer.py)** — currently plain `(today - due_date).days`.

### 9. Bill QR + invoice
**Missing · E4-S7** — `POST bills/qr/decode/` and `GET bills/<id>/invoice/`. The QR path **must** delegate to the shared [qr_strategy.py](../apps/vendors/services/qr_strategy.py) (AC: "shared parser, one code path"), not grow a second parser. Invoice renders from bill fields; no OCR in v1.

---

## P2 — E3 remaining stories

### 10. ABA routing validation
**Missing · E3-S9** — `POST banking/routing/validate/` currently **404s**; `apps/banking` does not exist. Needs the app, mod-10 ABA checksum, bank-name lookup, rate limiting. The vendor ACH form depends on it.

### 11. Vendor detail has no spend history
**Missing · E3-S4 · [apps/vendors/api/serializers/vendor.py](../apps/vendors/api/serializers/vendor.py)** — no 12-bucket monthly series, total paid (12 mo), next bill, or embedded bills with status chips. Partially blocked on E6 for payment amounts.

### 12. `summary.check_total` is hardcoded `0`
**Broken · E3-S2 · [apps/vendors/selectors/vendor_selector.py](../apps/vendors/selectors/vendor_selector.py)** — left as a `TODO`; needs bill/payment amounts from E6.

---

## P3 — E2, entirely unbuilt

All five stories. Nothing here has been started.

| # | Story | What's needed |
|---|---|---|
| 13 | **E2-S1** OTP channel + async delivery | `OTPChannel` enum + `channel` field on [OTP](../apps/authentication/models/otp.py) + migration. Delivery is currently **synchronous** via `EmailService`; move to a Celery `send_otp` task behind a `MessagingProvider` in `integrations/`. Reject `channel=SMS` explicitly (422/501) — no silent no-op. |
| 14 | **E2-S2** Resend throttle | 60s minimum gap + 5/hour per user+purpose; 429 with retry-after. No throttling exists. |
| 15 | **E2-S3** Phone login | `POST auth/login/phone/request/` and `.../verify/` both **404**. Reuse `OTPPurpose.LOGIN`; unknown phone must match unknown-email shape *and timing* (no enumeration). |
| 16 | **E2-S4** Password history | `PasswordHistory` model absent; reuse is unrestricted. Write on every set, reject match against last N, prune to 5. |
| 17 | **E2-S5** BaseAPIView alignment | All 9 auth views subclass raw `APIView`. Needs an `AllowAny` variant of [BaseAPIView](../apps/common/base_views.py); responses must stay byte-identical. |

---

## P4 — Cross-cutting

### 18. `manage.py test` discovers 0 tests
**Broken** — `apps/` has no `__init__.py`, so it is a namespace package and unittest discovery skips it entirely. Every test stub in the repo has never run. Fix is one empty file; explicit module paths work meanwhile:

```
manage.py test apps.bills.tests.test_recurrence
```

### 19. Date-engine tests cover only recurrence
**Missing · E1-S5** — Phase 1 added table-driven recurrence tests, but `add_business_days`, `is_business_day`, `us_federal_holidays`, `initiation_date` and `estimated_arrival` have **zero** coverage, despite the AC calling for "Fri+1=Mon, holiday skip" cases.

### 20. OpenAPI schema errors
**Debt** — 16 unique `unable to guess serializer` errors across `bills`, `payments`, `vendors`. Every plain `APIView` needs `@extend_schema`, as [bill_categories/schemas.py](../apps/bill_categories/schemas.py) already does.

### 21. `payments` app is still flat files
**Debt** — flat `views.py`/`serializers.py`/`urls.py`, against [file-architecture.md](file-architecture.md). Policy says convert when an epic touches it, so this lands with **E6**.

### 22. Tests are gitignored
**Decision needed** — [.gitignore:16](../.gitignore#L16) has a bare `tests/` with the comment *"Tests are kept local, not pushed"*. Deliberate, so I left it — but it means the 25 passing tests are not in the repo and CI could never run them. Narrowing the rule would change that.

---

## Already fixed (context only)

| Commit | Change |
|---|---|
| `0a23b37` | **E4 Phase 0** — extracted `apps/bills`; created the missing migration; registered `StandingAuthorization` (nothing imported it, so Django never saw it); fixed the `ImportError` in `bill_selector`, the missing `__init__` on both services, the missing `get_user_bills`, the missing `get_days_overdue`, and the clobbered `bill-categories/` route |
| `a66937f` | **E4 Phase 1** — occurrence engine + Celery beat; **fixed month-end drift in `next_occurrence`** (Jan 31 → Feb 28 → Mar 28, quarterly → Jul 30); read-time computed status; create-time seeding |
| `2bb4ee7` | **E1–E3 audit** — vendor soft-delete 500 (`ProviderStatus.DELETED` exists on no enum); `payee_verified` was client-writable; vendor filters silently ignored; no pagination anywhere; malformed QR returned 200; 110 lines of shadowed duplicate views; broken auth test |
| `43dc119` | **E3-S6** — per-method rail, lead time, initiation date, estimated arrival and `can_meet_due_date`; query params validated instead of dropped |
| `4915885` | **E4-S5** — schedule rebuild on `frequency`/`anchor_date` change; repricing on amount change (FIXED only); soft delete via `Bill.deleted_at` so paid history survives |

**E1 audited clean.** Celery, USD defaults, enums + state machine, `integrations/` (five providers with mocks + factory), `crypto.py` and `IdempotencyKey` are all correct.

**No raw bank data anywhere.** `grep -rE 'routing_number|account_number' apps/` returns nothing, and the ACH branch already uses the client-side tokenization shape the epic prefers over server relay.
