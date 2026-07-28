# E7 (Flo / AI Advisor) Recheck — what's missing to implement

**Date:** 2026-07-28 · **Scope:** `docs/epics/epic-7-ai-advisor.md` (E7-S1…S4)
**Method:** 5 parallel read-only audits (one per story + cross-cutting), each finding adversarially verified by an independent refuter, then a completeness critic. 58 findings survived verification, 17 were refuted. Deduped below; every P1 re-verified by hand.

## Headline

**All 4 stories are implemented and wired — 0 missing.** The arithmetic spine is right: every figure is computed in Python before any LLM is consulted, the response contract matches the spec exactly, no account numbers or raw transactions reach the provider, the kill switch exists and is honored, and the epic's central invariant holds.

The failures are concentrated in **the inputs to the arithmetic** (stale balances, a truncated bill horizon, committed money that is invisible) and in **the guard rails around the LLM** (echo-validation is defeatable, the timeout is 3× the AC).

| Story | Implemented | ACs met | Notes |
|---|---|---|---|
| E7-S1 Consent | ✅ | 1 / 3 | Model + migration match the spec byte-for-byte; gate is service-level; audit row quality is the problem |
| E7-S2 Cash context | ✅ | 1 / 3 | Figures correct & PII-minimized; echo-validation defeatable; no 2.5 s timeout |
| E7-S3 Projection | ✅ | 0 / 2 | Deterministic, but three separate reasons it is not "to the cent" |
| E7-S4 LLM behind flag | ✅ | 2 / 3 | Flag-off path is genuinely zero-call; timeout + missing `template.py` |

## Confirmed solid (the invariants hold)
- ✅ **No LLM in the money path.** `cash_context_service.py:38` is the only `get_llm_provider()` consumer in `apps/`. `apps/banking/services/recurring_detector.py:3` states "No LLM, by design". Nothing in payments/bills reaches the LLM layer.
- ✅ **Figures are computed pre-LLM** (`cash_context_service.py:43` before `:44`), so a prompt-injection-shaped vendor name cannot alter `figures` — **E7-S2 AC2 passes**.
- ✅ **Flag off → zero external calls.** `FLO_LLM_ENABLED` defaults `False` (`base.py:340`); the `anthropic` SDK is imported lazily inside `complete()` (`anthropic.py:25`), so nothing is constructed at import.
- ✅ **PII minimization.** The only payload is the rendered template sentence: balances, counts, vendor display name, due date. No account numbers, tokens, or raw transactions.
- ✅ **Model + migration match the spec exactly** (`advisor_consent.py:15-25` vs `0001_initial.py:21-31`), auth enforced on all three endpoints via `BaseAPIView`, routes match the spec paths.

---

## P1 — real defects · **all six fixed 2026-07-29**

Verified by a new suite: `apps/ai_advisor/tests/` (49 tests) and
`apps/banking/tests/test_balance_service.py` (6). Full run: **97 passed, 1
failed** — the failure is pre-existing and unrelated
(`apps/common/tests/test_integrations.py::test_serializers_free_of_processor_names`:
"Stripe" and "Moov" appear in `apps/vendors/api/serializers/`, an E6-S11
grep-gate violation that was simply invisible while the suite could not run).

1. **Balances are link-time snapshots that are never refreshed.** `available_balance` has exactly one writer in the repo — `apps/banking/services/link_service.py:112` — and `CELERY_BEAT_SCHEDULE` (`base.py:281-305`) has four jobs, none in banking. So E7-S2's headline "Chase balance $41,200" and E7-S3's `current_balance` are both as old as the bank connection. The epic's **"Blocked by: E5 (balances)"** is not actually satisfied. `BankAccount.balance_as_of` exists (`bank_account.py:42`) and E5's own serializer surfaces it, but neither E7 response carries it — the client cannot even caveat the number. **Fix:** refresh on read (or a beat job), and add `balance_as_of` to both E7 payloads.

2. **The projection outruns E4's materialization horizon and silently returns zero outflow.** `BillOccurrenceService.HORIZON_CYCLES = 2` (`bill_occurrence_service.py:20`), so occurrences exist only ~2 cycles ahead — measured today: monthly = +49 days, weekly = +13 days, quarterly = +166 days. `BalanceProjectionQuerySerializer.date` (`serializers/projection.py:8`) accepts any future date. Ask for 120 days out and `projection_service.py:51-56` subtracts **nothing** past the horizon, then reports `sufficient: true`. The error is silent and grows with distance. This breaks **E7-S3 AC1 ("to the cent")** independently of the missing test. **Fix:** clamp `date` to the materialized horizon, or materialize on demand, and return the horizon in the response.

3. **Committed money is invisible, so the projection overstates funds.** `open_occurrences` excludes SCHEDULED/PAID (`occurrence_status.py:46-48`), and `payment_create_service.py:98` marks an occurrence SCHEDULED at *creation* — before execution, per its own docstring. That money has left neither the account nor the outflow. Worse, `apps/ai_advisor` **never imports `Payment` at all**: future-dated sends (`payment.py:134 scheduled_for`) against `funding_account` (`:65`), and vendor-only payments where `bill_occurrence` is null (`:49-54`), have no occurrence to include under any filter fix. **Fix:** union open occurrences with not-yet-settled `Payment` rows for the account, deduped on `bill_occurrence_id`.

4. **Echo-validation is sign-blind and defeated by magnitude collision.** `_MONEY` (`cash_context_service.py:27`) requires `$` immediately before digits, so it never captures a minus sign, while `known` (`:156-162`) holds signed Decimals. Executed against the real regex:
   - `"You will have $1,000.00 left over."` **passes** when `balance_after` is **−$1,000** — because `1000` is legitimately in `known` as `upcoming_total`. A user who is $1,000 overdrawn is told they have $1,000 spare, and the guard signs off. Overdraft is precisely the state the advisor exists to warn about.
   - The template's own overdraft rendering is `$-1,000.00` (`:100`) — malformed currency, and `findall` returns `[]` on it, so the figure that matters most is unvalidatable by construction.
   - Bare numbers (`"41200 dollars"`), percentages (`"95% covered"`), and **empty/whitespace output** all pass and are served verbatim (`:129`).
   - `known` is an unordered set, so swapping `balance_now` and `balance_after` passes.
   **Fix:** validate all numerics (not just `$`-prefixed), compare per-slot rather than set-membership, reject empty output, and render negatives as `-$1,000.00`.

5. **The consent audit record fabricates the client IP.** `consent_service.py:68` files `ip or "0.0.0.0"` and `views/consent.py:14` reads `REMOTE_ADDR` directly — behind a load balancer that records the balancer. The house utility built for exactly this, `apps/common/request_meta.py:18-24`, says: *"Callers persisting a consent artifact should treat `None` as a hard failure rather than substituting a placeholder — a consent record with a fabricated IP is worse than no record."* This is the GLBA/CA/VT opt-in artifact. **Fix:** use `request_meta(request)`; fail the write rather than fabricate.

6. **The epic ships with zero tests.** No `apps/ai_advisor/tests` package; no test anywhere references `ConsentService`, `CashContextService`, or `ProjectionService`. Four ACs name a test explicitly (S1-AC2 "tested", S2-AC1, S3-AC1 fixture, S4-AC1 network-recording, S4-AC3 contract test). Compounding: there is **no `pytest.ini` / `pyproject.toml` / `setup.cfg` / `conftest.py` anywhere in the backend**, so `pytest-django` has no `DJANGO_SETTINGS_MODULE` and the suite cannot bootstrap at all.

## P2 — AC violations and correctness gaps

7. **No 2.5 s timeout.** `anthropic.py:18` hardcodes 8 s, and the SDK retries twice by default → worst case ~25 s against an AC of **p95 ≤ 2.5 s (timeout → template)**. Not env-tunable. **Fix:** timeout ≈ 2 s, `max_retries=0`, budget enforced by the caller.
8. **`integrations/llm/template.py` does not exist** (spec line 36 names it as the default). The template lives inside `CashContextService._template`, and the registered default is `MockLLMProvider`, whose output is `"[mock-llm] " + prompt` (`mock.py:11`). Flipping `FLO_LLM_ENABLED=true` on a default install therefore serves literal `"[mock-llm] Balance $41,200.00…"` to real users — it passes echo-validation, since the numbers match.
9. **Daily cap is per-process and non-atomic.** No `CACHES` is configured in any settings module, so Django falls back to per-process LocMemCache: the real ceiling is `N_workers × cap`. `get`/`set` is racy (`cash_context_service.py:147-151`), and quota is consumed even when the call later fails.
10. **Date math is UTC, not ET.** `TIME_ZONE = "UTC"` (`base.py:228`), so `timezone.localdate()` rolls at 19:00/20:00 ET. Evening-ET requests reject *today* as a past date (`projection_service.py:30`) and drop bills due today. The epic routes date math through E1-S5; neither E7 service uses it.
11. **Overdue unpaid bills are excluded from the projection outflow** (`bill_occurrence_selector.py:32` filters `due_date__gte=today`). Defensible for E7-S2's "upcoming" (and refuted there), but for a *balance projection* money still owed must come out.
12. **`upcoming_total` has no window at all** (`cash_context_service.py:72`) — it sums every open occurrence, so the total is an artifact of each bill's cadence (a weekly bill contributes 13 days of obligations, a quarterly one 166). The screen copy "enough to cover all 4 upcoming bills" presumes a defined near-term set.
13. **The sufficiency sentence double-counts the bill being paid.** `balance_after = balance_now − amount` (`:88`) while `upcoming_total` still contains that same occurrence, then `:97` compares the two. Errs conservative (says "short of" when solvent), but the arithmetic is wrong.
14. **Response envelope inconsistency.** All three E7 views return bare `Response(serializer.data)`, while errors route through `exception_handler` → `ApiResponse.error`. One endpoint, two body shapes; 13 other modules use the `{success, message, data}` envelope.
15. **No `GET ai/consent/`.** The spec assumes a settings surface (line 24), but consent state is unreadable — no read route, and no serializer outside `apps/ai_advisor` exposes it. A settings screen cannot render the toggle without POSTing, which itself grants consent.
16. **`apps/audit` is a write-only sink.** `admin.py` and `views.py` are untouched stubs, there is no audit URL module, and `AuditLog.Meta` declares only `db_table` — no index on `user`, `action`, or `created_at`. Rows are inserted and cannot be retrieved by anyone. For a GLBA opt-in artifact, "recorded in the audit trail" means producible on demand.

## P3 — completeness / polish

17. Unknown account returns **404 where E7-S3 AC2 specifies 422** (`projection_service.py:47`). The code deliberately merges unknown-vs-foreign to prevent enumeration — a reasonable call, but it contradicts the AC. **Decide: fix the code or amend the spec.**
18. `anthropic` is **not in `requirements.txt`**, so the flagged path cannot run in any built image; nothing validates the flag/key pairing at boot.
19. None of the five E7 env flags appear in `.env.example`.
20. No `@extend_schema` on any E7 view — three endpoints missing from the OpenAPI schema.
21. Re-consent overwrites `consented_at` and `revoked_at` (`consent_service.py:31-38`), destroying the history the model docstring claims to keep, and appends a duplicate audit row. E4's precedent short-circuits instead (`bills/services/consent_service.py:92`).
22. `consent_text` is `required=False, allow_blank=True`, so an omitted field persists a server-side default as the "exact language shown".
23. Django admin can **delete** consent rows; `add` is reachable but guaranteed to fail (`consented_at` is readonly and non-null).
24. Vendor name is interpolated into the prompt unsanitized and untruncated (`:107`). `figures` are safe, but `text` is not.
25. No throttle on `ai/cash-context/`, the cost-bearing endpoint. A fresh Anthropic client is built per call.
26. Redundant queries: `get_next_due` re-fetches the row already at the head of `upcoming` (`:72`/`:77`). Template copy reads `"bill(s)"` and degenerates at zero bills.

---

## Refuted — do not chase
The verification pass killed 17 findings. The notable ones: `LLM_PROVIDER="template"` does **not** 500 (the default is `"mock"`); the `lte` projection boundary is **documented and correct**, not an off-by-one; the zeroed recurring-inflow term is **what the spec asks for** ("if any" — E5 detects outflows only, and `scan_service.py:7` persists no transactions); outflow not being account-scoped is **unavoidable** (no bill→account relation exists in the schema); `available_balance=None` is **unreachable** (`link_service.py:105-116` always writes it); and `sufficient` is **algebraically identical** to the cash-context check.

---

## What was fixed (2026-07-29)

| # | Fix | Files |
|---|---|---|
| 1 | `BalanceService` re-reads the balance through the provider on a TTL (`BALANCE_MAX_AGE_SECONDS`, default 300 s); a provider failure keeps the stored value and its stamp. Both E7 responses now carry `balance_as_of`. | `apps/banking/services/balance_service.py` (new), both E7 services + serializers, `config/settings/base.py` |
| 2 | `BillOccurrenceService.due_dates_through()` walks the recurrence rule read-only, so the projection is exact past E4's two-cycle horizon. `date` is capped at `MAX_PROJECTION_DAYS = 730`. | `apps/bills/services/bill_occurrence_service.py`, `projection_service.py`, `serializers/projection.py` |
| 3 | The projection subtracts live `Payment` rows (SCHEDULED/PENDING/PROCESSING) against the funding account, deduped on `bill_occurrence_id`, and reports them as `committed_total`. Catches ad-hoc payments with no occurrence. | `apps/ai_advisor/services/projection_service.py` |
| 4 | Echo-validation compares the **multiset of every numeral** — signed, `$`-prefixed or bare, percentages kept distinct — against the template's. Empty output is rejected. Negatives render `-$1,000.00`. | `apps/ai_advisor/services/cash_context_service.py` |
| 5 | Consent uses `request_meta` (X-Forwarded-For first). Granting **refuses** when the IP is unknown rather than filing `0.0.0.0`; revoking is never blocked and records a null IP honestly (`AuditLog.ip` is now nullable). | `consent_service.py`, `api/views/consent.py`, `apps/audit/` + migration `0002` |
| 6 | `pytest.ini` (`DJANGO_SETTINGS_MODULE`), a test settings module that runs on SQLite with every provider pinned to mock, and 55 new tests. `POSTGRES_*` got defaults so settings import without a `.env`. | `pytest.ini`, `config/settings/{base,test}.py`, `apps/ai_advisor/tests/`, `apps/banking/tests/` |

**Found while fixing #4 and also fixed:** an injection-shaped *vendor name* put a
dollar figure Flo never computed into Flo's own sentence — with no LLM in the
path at all, since the name is interpolated into the template. `_vendor()` now
strips currency framing and truncates for display; `figures.next_bill.vendor`
still carries the real name as data for the client.

Two migrations (`payments/0006`, `0007`) that drop the removed wallet and
payment-tracking tables used Postgres-only `DROP … CASCADE`. They are now
no-ops on any other backend — the Postgres path is byte-identical, and those
tables never existed on a fresh test database.

## Suggested order for what remains
1. **P2 #7–#9** — the LLM guard rails, before `LLM_PROVIDER=anthropic` is ever switched on.
2. **P2 #10–#16**, then **P3**.
3. Fix the pre-existing processor-name leak that the now-runnable suite exposes.
