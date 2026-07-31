# Swayp Backend — Backlog (Epics & Stories)

Derived from [PRD.md](../PRD.md) (v2.0, reconciled with the CEO **BRD**) and dashboard-plan.md. Every story is a **vertical slice** (models → service → API) and carries its exact ORM plan, endpoints, screens, and acceptance criteria — implementable without reopening the plan.

> ⚠️ **BRD reconciliation (2026-07-17):** rails are **Stripe (configured-account) + Moov (ACH) + Lob/PostGrid (checks)** — Dwolla/GoCardless/Stripe-Treasury excluded. Raw bank numbers are **never stored** (tokenized at Moov; masked + reference only). **Non-custodial** is a hard invariant. **USD only.** **Email only** this release. E9 (Billing) and E10 (Teams) are new. See [PRD §0](../PRD.md).

**Conventions:** models follow `BaseModel` (UUID pk, `created_at`/`updated_at`); money = `DecimalField(18,2)` USD; layering + per-feature file packages per [file-architecture.md](../file-architecture.md); every list endpoint paginated + filtered; all third parties behind `integrations/` interfaces with mocks.

## Epic index

| Epic | Title | Release | Blocked by |
|---|---|---|---|
| [E1](epic-1-foundations.md) | Platform Foundations | R1 | — |
| [E2](epic-2-authentication.md) | Authentication & Accounts | R1 | E1 (Celery for OTP delivery) |
| [E3](epic-3-vendors.md) | Vendor Management | R1 | E1 |
| [E4](epic-4-bills.md) | Bill Management & Occurrences | R1 | E3 |
| [E5](epic-5-banking-onboarding.md) | Bank Connection & Onboarding | R2 | E1, E3, E4 |
| [E6](epic-6-payments.md) | Payments & Money Movement | R3 | E1, E4, E5 |
| [E7](epic-7-ai-advisor.md) | Flo — AI Cash Advisor | R3 | E5 (balances) |
| [E8](epic-8-dashboard-reports-notifications.md) | Dashboard, Reports & Notifications | R1–R3 | E3, E4 (E8-S1); E6 (E8-S4) |
| [E9](epic-9-billing.md) | Billing & Subscriptions | R2 | E1 |
| [E10](epic-10-teams.md) | Teams & Entities | R2 (seats) / later (Enterprise) | E1, E2 |

## Story map (summary)

```
E1  S1 Celery wiring        S2 USD currency fix     S3 Enums+state machine  S4 Provider interfaces
    S5 Business-day engine  S6 Encryption/masking   S7 IdempotencyKey
E2  S1 OTP channel+delivery S2 Resend throttle      S3 Phone login pair     S4 Password history   S5 BaseAPIView alignment
E3  S1 Vendor models        S2 List+summary+search  S3 Create (3 branches)  S4 Detail+spend
    S5 Edit/delete          S6 Payment-methods API  S7 Directory search     S8 QR decode          S9 ABA validate
E4  S1 Bill models          S2 List+summary         S3 Create wizard        S4 Detail+history
    S5 Edit/delete          S6 Occurrence engine    S7 QR+invoice           S8 Next-due
E5  S1 Banking models       S2 Link+exchange        S3 Connections+accounts S4 Scan+detection
    S5 Candidates+import    S6 Onboarding summary
E6  S1 Payment models       S2 Create+batch         S3 Confirm+authorize    S4 Status+detail
    S5 Cancel               S6 Failure+resolve      S7 Execution engine     S8 Webhooks+dedupe
    S9 Autopay+REMIND loop  S10 Deprecations
E7  S1 Consent              S2 Cash context         S3 Balance projection   S4 LLM behind flag
E8  S1 Home aggregate       S2 Reports (+1099)      S3 Notification types+prefs  S4 Reminder jobs
E9  S1 Plan+Subscription    S2 Allowance counters   S3 Per-txn fees+overage      S4 Delivery-guarantee refunds  S5 Enterprise add-on items
E10 S1 TeamMember+seats     S2 Invitations          S3 Entity (multi-entity)     S4 Approval workflows+ERP (later)
```

## Definition of Done (every story)
- [ ] Code follows [file-architecture.md](../file-architecture.md) (feature files, layering, re-exports)
- [ ] Migrations included; `manage.py check` + `makemigrations --check` clean
- [ ] OpenAPI schema generates without new errors; endpoints documented
- [ ] Tests: serializer validation + service behavior + route smoke (per feature file)
- [ ] No unmasked bank identifiers in any response (assert in tests)
- [ ] Feature-flagged if it touches a provider interface
