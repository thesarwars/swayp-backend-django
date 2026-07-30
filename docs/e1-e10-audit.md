# E1–E10 Audit

A verification pass over every epic and every route, run against the live API
rather than read off the code.

**Method.** Two smoke passes exercised all 88 registered routes — reads,
writes, deletes, terminal transitions and all five webhooks — against a
realistic Enterprise account with a bank, vendor, bill, occurrences and a team.
Every non-2xx was then opened and checked against the epic's stated behaviour,
because a wrong-but-plausible 400 is exactly what this kind of audit exists to
catch.

**Result.**

```
94 calls · 0 server errors · 806 tests · makemigrations --check clean
```

Every non-2xx is a correct refusal. Details below.

---

## 1. Route coverage per epic

| Epic | Routes | Status |
|---|---|---|
| **E1** Foundations | — (date engine, idempotency, audit, providers) | ✅ exercised through every other epic |
| **E2** Authentication | 11 | ✅ |
| **E3** Vendors | 8 + `routing/validate/` | ✅ |
| **E4** Bills | 12 + `bill-categories/` | ✅ |
| **E5** Banking onboarding | 11 | ✅ |
| **E6** Payments | 14 + 5 webhooks | ✅ |
| **E7** AI advisor | 3 | ✅ |
| **E8** Dashboard / reports / notifications | 8 | ✅ |
| **E9** Billing | 6 | ✅ |
| **E10** Teams | 7 | ✅ |

**88 routes total** (83 under `/api/v1/`, 5 versionless webhooks). Every one
declared in an epic exists, and every one that exists was called.

---

## 2. Non-2xx responses, and why each is correct

None of these is a defect. They are listed because "it returned 400" is not
self-evidently right, and each was checked.

| Response | Endpoint | Why it is correct |
|---|---|---|
| **501** | `auth/resend-otp/` with `channel=SMS` | **E2 AC**: *"`channel=SMS` rejected (422/501) while SMS is deferred — no silent no-op."* The message names EMAIL as the alternative. |
| **405** | `reports/?export=csv` | **E8 AC**: the export format is PRD §10-Q4 and undecided, so the hook refuses rather than guessing CSV or PDF. |
| **403** | `reports/1099/` on Founding | **E8/E9**: 1099 is Standard-plan. Returns 200 once the account is on Standard — the E8→E9 entitlement seam works end to end. |
| **403** | `PATCH payments/<id>/processing\|successful\|failed/` | **E6-S4**: these transitions are internal, so the routes are staff-only. |
| **400** | `webhooks/moov\|stripe\|lob\|plaid/` | **E6-S8**: a processor with no signing secret configured is *refused, not trusted*. Fail-closed. Real secrets arrive with the provider accounts. |
| **400** | `vendors/<id>/payment-methods/` with raw bank numbers | **BRD §3.4**, and the most important one here: the API demands `provider`, `provider_token` and `account_last4`. Raw routing and account numbers are refused at the boundary, so they can never be stored. |
| **400** | `payments/batches/<id>/confirm/` after cancel | A cancelled batch cannot be authorized. |
| **400** | `payments/<id>/resolve/` on a cancelled payment | Nothing to resolve; resolution applies to failures. |
| **400** | `payments/<id>/failure/` on a healthy payment | There is no failure to report. |
| **400** | `ai/cash-context/`, `ai/balance-projection/` | Required fields (`amount`; `account` + `date`) missing from the probe. |
| **400** | `notifications/preferences/` | Requires a `preferences` object. |
| **400** | `bills/occurrences/<id>/pay/` | Requires `payment_reference` — marking a bill paid by hand has to say what paid it. |

---

## 3. Background work

Every Celery task either runs on the beat schedule or has a caller. Checked
because this is how the free-check reset was found missing.

| Task | Trigger |
|---|---|
| `bills.generate_occurrences` | beat, 03:00 |
| `payments.autopay_scheduler` | beat, 04:00 |
| `payments.release_scheduled_payments` | beat, 04:30 |
| `payments.reconcile_payments` | beat, hourly :15 |
| `notifications.bill_status_notifier` | beat, 05:00 |
| `billing.renew_subscriptions` | beat, 00:30 |
| `authentication.send_otp` | register / login / resend |
| `teams.send_team_invite` | team invite |
| `notifications.send_notification_email` | `notify()` |
| `payments.execute_payment` | payment confirm, autopay |
| `banking.sync_transactions` | scan start |
| `common.health_check` | liveness probe, unscheduled by design |

No orphans.

---

## 4. Deliberately not built

Each is deferred by its own epic or blocked on something outside the codebase.
None is an oversight.

| Item | Source |
|---|---|
| **E10-S4** approval workflows + ERP sync | Epic: *"Deferred beyond R4 — confirm scope (PRD §10-Q10)."* The $99/$149 add-ons are sellable but inert. |
| **SMS / push notifications** | BRD §1.2 — email + in-app this release. Columns reserved, no adapters. |
| **Report export format** | PRD §10-Q4 — CSV vs PDF undecided; the hook 405s. |
| **Stripe subscription billing** | Credentials not provided. Cycles roll and fees accrue; nothing settles. |
| **Proration** on mid-cycle plan change | Product decision. No credit is given today. |
| **Per-rail delivery SLA** | PRD §10-Q9. The guarantee currently measures against the arrival shown to the customer. |

---

## 5. Known defect, not from this branch

`apps/common/tests/test_integrations.py::test_serializers_free_of_processor_names`
fails because `apps/vendors/api/serializers/provider.py:21` returns the literal
`"Stripe"` from a serializer method, and
`vendor_payment_method.py:99` mentions "Moov" in a comment. Both were
introduced in commit `0edad64`.

The test asserts a real product rule — a processor name must not reach an API
response except inside NACHA authorization text. Either the serializer leaks or
the test is too broad. **This needs a decision from whoever wrote it**; it has
not been changed unilaterally.

It is the only failing test in the suite.

---

## 6. What this audit found and fixed

Seven defects, five of them in code that had already been committed and was
passing its own tests. They share one shape — **a green unit test sitting over
a call site that was wrong or absent** — which is why the tests written during
this work drive the API rather than the service.

1. **Free checks never reset.** The metered counter keys on `period_start` and
   nothing advanced it. A Founding customer would have received 2 free checks
   *ever* instead of 2 a month, with every one after billing $2.99. A live
   overcharge, and E9-S2's own acceptance criterion.
2. **The $8.99 expedited check was unreachable.** No API field existed and the
   flag was read from `failure_detail`, a diagnostics blob nothing wrote to.
3. **The delivery-guarantee refund could never fire.** It compared
   `estimated_arrival` against itself — false by construction — and ran at
   send, when nothing is late yet.
4. **The fee guaranteed a later date than the customer was shown** (09-04 vs
   09-01), failing in the direction that costs the customer.
5. **A team member could have started a second subscription** on their own user
   while the owner kept paying for the first.
6. **`GET /payments/history/` returned 500** for any payment with no provider
   or category. It fails while rendering, so one bad row hid the entire page.
   Pre-existing since E6-S1.
7. **Bank and seat usage disagreed with the gate** — the billing screen showed
   "0 of 1 used" while the button returned 402.
