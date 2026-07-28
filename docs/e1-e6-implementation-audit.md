# E1–E6 Implementation Audit — what's missing to implement

**Date:** 2026-07-18 · **Branch:** `master` @ `d954f4c` (post epic6/payment-models merge)
**Method:** 6 parallel read-only audits, one per epic, each checking every story's acceptance criteria against the actual code.

## Headline

**All 46 stories across E1–E6 are implemented — 0 entirely missing.** The gaps are (1) **automated tests** (by far the largest) and (2) a short list of **specific functional defects / completeness gaps**. One item is **actually broken on the branch** (breaks test collection).

| Epic | ✅ | 🟡 Partial | ❌ | Notes |
|---|---|---|---|---|
| E1 Foundations | 4 | 3 | 0 | Celery, enums+state machine, providers, date engine solid |
| E2 Authentication | 3 | 2 | 0 | OTP email/channel, phone login, password history done |
| E3 Vendors | 4 | 5 | 0 | **No raw bank numbers stored (BRD §3.4 ✅)** |
| E4 Bills | 6 | 2 | 0 | Occurrence model + consent capture solid |
| E5 Banking | 4 | 2 | 0 | 12-month scan + encrypted token confirmed |
| E6 Payments | 7 | 4 | 0 | Non-custodial holds architecturally |
| **Total** | **28** | **18** | **0** | 46 stories present |

## Confirmed solid (BRD invariants hold)
- ✅ **No raw routing/account numbers stored anywhere** — `VendorPaymentMethod` has only `provider_token` + `account_last4` + `aba_bank_name`; the routing-validate input is `write_only`, never persisted (BRD §3.4).
- ✅ **Non-custodial** — execution orchestrates only; no funds rest in a Swayp balance; wallet debit/credit stripped; every `Payment` records `processor` + `provider_reference`; processor names confined to `authorization_text`.
- ✅ **12-month** scan window (not 24); Plaid `access_token` is Fernet-encrypted and never serialized.
- ✅ Payment **state machine** transitions correct + exhaustively tested; **business-day/DST date engine** table-tested; **Celery** wired with `America/New_York`; **BillOccurrence** mandatory with read-time status.

---

## P0 — actually broken (fix first)
1. **`apps/payments/tests/test_currency_default.py:5` imports the deleted `apps.wallet.models.Wallet`** → the module fails at pytest collection, which can abort the whole test run. It's also the only live `wallet` import outside migrations, so it violates E6-S11's grep-gate AC. **Fix:** rewrite the test to assert USD on `Payment` only (drop the Wallet import), since the wallet subsystem was removed.

## P1 — functional defects (wrong/missing behavior, not just tests)
2. **E6-S8 — late ACH return sets the occurrence to `UPCOMING`, but it should be `DUE`** (`webhook_service._apply_return`; contradicts the AC *and* the method's own docstring). A reversed bill shows the wrong status.
3. **E5-S3 — `DELETE banking/connections/<id>/` doesn't revoke at the provider.** `disconnect()` only flips the local status; `BankDataProvider` has no revoke method. A "disconnected" bank stays live at Plaid. **Fix:** add `revoke_item()` to the interface + mock and call it.
4. **E3-S7 — directory-search isn't behind the provider interface.** The endpoint queries `providers.Provider` directly; `MockDirectoryProvider` exists but is **dead code** (zero references). Also missing the `verified`/`network` result fields and the "cache upsert into providers.Provider" the spec calls for.
5. **E3-S6 — payment-method PATCH lacks the E1-S6 masked-field rules** (no `*`-rejection, no "omitted = unchanged") and **no ACH re-tokenization** on account change (relies entirely on the client sending a fresh token).
6. **E3-S5 — no guard blocking vendor soft-delete when live/scheduled payments exist** (`soft_delete` deletes unconditionally); the spec's "blocked message" is absent.
7. **E6-S7 — `assert_non_custodial()` is defined but never called** (dead code). The invariant holds by construction but is enforced nowhere at runtime. **Fix:** invoke it as a guard in the execution path.

## P2 — completeness gaps (sub-features named in the spec)
8. **E3-S2** — vendor list rows omit **recurring amount + period** and **next-due** (both required by the row spec / dashboard).
9. **E3-S4** — vendor detail returns only a single `next_bill`, not the **capped embedded bills list with status chips**.
10. **E2-S4** — the **register path doesn't write a `PasswordHistory` row** (reset-reuse detection still works via the live-password fallback, so it's a completeness gap, not a correctness bug).
11. **E2-S5** — auth views subclass `PublicAPIView` but **`service_class`/`ServiceMixin` is inert** (services are called directly); no `selectors/`; response envelopes are inconsistent (`phone_login` uses `ApiResponse.success`, others return raw dicts).
12. **E6-S10** — `providers/search/` is still active and **not marked `deprecated=True`** (spec says it's superseded by E3-S7).
13. **E1-S6 / E3-S1** — no **CI grep-gate** asserting DB/logs contain no routing/account numbers, and none asserting `EncryptedTextField` is limited to provider secrets (code is compliant; the *enforcement* AC is unmet).

## P3 — polish / consistency
14. **E4 REST paths deviate from the spec:** list/create/detail/update live at `bills/`, `bills/create/`, `bills/<id>/details/`, `bills/<id>/update/`; the occurrence-backed list is at `bills/occurrences/`; and bare `GET bills/` returns an **unpaginated** Bill list. Align routes to the spec, or update the spec.
15. **E2-S1** — SMS-channel rejection returns **400** instead of the spec's 422/501 (hard reject either way).
16. **E3-S1** — model `clean()` is defined but **never invoked** on the API write path (validation only at the serializer); orphan/unused `VendorMailingDetail` scaffolding in `models/bank.py` + `models/mailing.py` should be removed.
17. **E6-S8** — webhook handling runs **inline in the view**, not the "enqueue-and-ack" the base docstring claims (fine for mock; revisit for real providers) .
18. **E2** — `phone_login` views/serializers aren't re-exported from their package `__init__.py` (routing works via direct import, but breaks the re-export convention).

---

## The dominant gap: tests
Test suites exist **only** for `apps/common` (dates, crypto, integrations, tasks) and `apps/payments` (state machine, idempotency — and `test_currency_default.py` is broken). **`authentication`, `vendors`, `banking`, and `bills` have zero tests.** Consequently, almost every "🟡 Partial" above is *"behavior implemented, but the AC-named test is missing."* The highest-risk untested paths:
- **Money safety (E6):** no kill-worker/no-duplicate-debit test, no reconciliation test, no webhook dedupe / out-of-order / bad-signature / late-return tests, no cancel-deadline boundary test.
- **Consent/NACHA (E4):** standing-authorization capture/revoke untested.
- **Detection (E5):** the golden recurring-detection fixture is purpose-built but unverified.
- **Auth (E2):** throttle gap/cap and password-reuse untested.

## Out of scope of this audit (not yet implemented — separate epics)
`E7 Flo/ai_advisor`, `E8 reports + notification-preferences`, `E9 billing/subscriptions`, `E10 teams/entities` — no `ai_advisor`/`reports`/`billing`/`teams` apps exist yet. These were never part of the merged epic6 branch.

## Suggested order
1. **P0** (unbreak the test suite) → 2. **P1** functional defects → 3. stand up **test suites** for auth/vendors/banking/bills + the E6 money-safety tests (largest effort, highest risk) → 4. **P2** completeness → 5. **P3** polish.
