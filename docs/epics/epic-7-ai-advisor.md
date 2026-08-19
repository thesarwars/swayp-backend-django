# E7 — Flo (AI Cash Advisor)

**Goal:** **Flo** — the "AI Cash Context" panel and balance projections — **arithmetic in Python, LLM phrases only**, consent-gated, template fallback so it ships without any LLM account. (Flo is the product name for the advisor across the app; BRD §3.1/§6.2.)
**Release:** R3 · **Blocked by:** E5 (balances), E4 (upcoming bills) · **New app:** `apps/ai_advisor` (API prefix `ai/`)
**Screens:** 840:27719, 840:28151, 841:29742

> Recurring-bill detection is **not** in this epic — it is deterministic clustering in E5-S4. Never put an LLM in the money path.

---

## E7-S1 · Consent — `POST ai/consent`, `DELETE ai/consent`

**As a** user **I opt in** before any financial data reaches an AI provider (GLBA/CA/VT opt-in posture — Part 1 doc) **and can revoke**.

**ORM (`apps/ai_advisor/models/advisor_consent.py`):**
```python
class AdvisorConsent(BaseModel):
    user         = OneToOneField(settings.AUTH_USER_MODEL, CASCADE, related_name="advisor_consent")
    consented_at = DateTimeField()
    revoked_at   = DateTimeField(null=True, blank=True)
    consent_text = TextField()            # exact language shown
    class Meta: db_table = "advisor_consents"
```
*(Settings surface assumed — PRD §10-Q12.)*
**AC:**
- [ ] AI1/AI2 return template-only output when no live consent (never 500)
- [ ] Revoke stops LLM calls immediately (service-level gate, tested)
- [ ] Consent recorded in `audit` app trail

## E7-S2 · Cash context — `POST ai/cash-context`

**As a** user about to pay **I see** "Chase balance $41,200; after this payment $38,000 — enough to cover all 4 upcoming bills; next: Verizon $389 Dec 15" (840:27719) and the authorization context on confirm (840:28151).

**Design:**
- `CashContextService` computes **all numbers in Python**: current balance (E5), balance-after, upcoming occurrence count/total (E4), next bill (E4-S8).
- `LLMProvider` (E1-S4: `template.py` default, `anthropic.py` flagged) receives **PII-minimized aggregates only** (no account numbers, no raw transactions) and returns one sentence.
- Response = `{text, figures: {balance_now, balance_after, upcoming_count, upcoming_total, next_bill}}`; client renders figures from `figures`, never parses `text`.
- Echo-validation: numbers appearing in `text` must match `figures` or fall back to template. Kill switch env flag.
**AC:**
- [ ] Template mode passes all tests with zero LLM calls
- [ ] Prompt-injection-shaped vendor names cannot alter figures (figures computed pre-LLM)
- [ ] p95 ≤ 500 ms template / ≤ 2.5 s LLM (timeout → template)

## E7-S3 · Balance projection — `GET ai/balance-projection?account=<id>&date=<d>`

**As a** user scheduling a payment **I see** "Projected balance on Dec 18: $44,100 — more than enough" (841:29742).

**Design:** deterministic forecast: current balance − upcoming occurrences due before `date` + known recurring inflows (from E5 detection, if any). Date math via E1-S5. No LLM required (phrasing optional via E7-S2 path).
**AC:**
- [ ] Fixture scenario matches expected projection to the cent
- [ ] Past dates / unknown account → 422; foreign account → 404 (ownership check)

## E7-S4 · Real LLM behind flag

**As** ops **we enable** Claude only when `LLM_PROVIDER=anthropic` + key present (+ signed DPA per Part 1).

**Work:** `integrations/llm/anthropic.py` (model from env, e.g. `claude-haiku-4-5` for this one-sentence task), structured-output request, retries/timeout → template fallback; per-user daily call cap.
**AC:**
- [ ] Flag off → zero external calls (network-recording test)
- [ ] Provider errors invisible to users (fallback text served)
- [ ] No PII fields present in outbound payload (contract test on the DTO)
