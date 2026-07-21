# Swayp Backend — Documentation Index

> All docs in this folder are **local planning docs** (`docs/` is gitignored — see repo `.gitignore`).

| Doc | What it is | Read it when |
|---|---|---|
| [Swayp BRD Payments.docx.md](Swayp%20BRD%20Payments.docx.md) | **CEO Business Requirements — authoritative** for payments/bank-connectivity business logic | anything money-movement; when a screen and the BRD disagree |
| [PRD.md](PRD.md) | Product Requirements (v2.0, BRD-reconciled) — goals, personas, FR/NFR, release phasing, open questions | scoping anything; talking to the client |
| [epics/](epics/README.md) | **Backlog** — 10 epics, ~50 stories, each with exact ORM models, endpoints, screens, acceptance criteria | cutting tickets / implementing |
| [file-architecture.md](file-architecture.md) | Repo structure convention — per-feature packages (`serializers/user_registration.py`), layering rules, app templates, planned apps | writing any code |
| [dashboard-plan.md](dashboard-plan.md) | Full technical plan (Part 2, BRD-reconciled) — screen→feature map, data model, complete API surface, Celery jobs, phasing | needing rationale/details behind a story |
| [third-party-services-and-production-requirements.md](third-party-services-and-production-requirements.md) | Part 1 (v2.0, BRD-reconciled) — services (Plaid/Moov/Stripe/Lob/Flo), client production asks, compliance, non-custodial fund flow | vendor decisions; production readiness |
| [figma_node.md](figma_node.md) | Authoritative list of the 68 Figma screens (node links) | tracing a screen id |

## Reading order for a new engineer
1. [PRD.md](PRD.md) §1–3 (what we're building) → 2. [file-architecture.md](file-architecture.md) (how code is laid out) → 3. your epic in [epics/](epics/README.md) → 4. [dashboard-plan.md](dashboard-plan.md) for deep rationale.

## Standing decisions (from the CEO BRD — do not re-litigate)
- **Rails decided (BRD §5)** — **Stripe** (configured-account vendors) + **Moov** (ACH) + **Lob/PostGrid** (checks). **Dwolla / GoCardless / Stripe-Treasury / BILL.com / Melio are excluded on record.**
- **Non-custodial (BRD §4)** — funds never rest in a Swayp balance; every payment is executed by a named licensed provider; written legal opinion required before the Moov path goes to production.
- **No raw bank data (BRD §3.4)** — raw routing/account numbers are **never stored** (not even encrypted); tokenized at Moov, masked last-4 + provider reference only. Field encryption is for provider secrets (Plaid token) only.
- **Provider owns screening (BRD §4)** — vendor KYB / sanctions / fraud is the provider's job; Swayp does only lightweight customer verification at sign-up.
- **USD only (BRD §3.5)** — enforced at the data layer; BDT defaults (Payment + Wallet) are a bug to fix (E1-S2).
- **Email only this release (BRD §1.2)** — SMS/push deferred.
- **Occurrence-based bills** — statuses/tabs/counts are per-occurrence; `Bill` stores no mutable status.
- **Consent records** — per-payment/batch authorization + standing authorization for auto-pay; immutable.
- **Timezone** — money deadlines & beat jobs in America/New_York (aware datetimes, never fixed "EST").
- **File convention** — per-feature packages; no Claude co-author trailers on commits.

## Open client questions
The BRD **resolved** the former blockers (rails, custody, directory, currency, fee model, SMS). Remaining items are in [PRD §10](PRD.md) — e.g. Stripe configured-account discovery, cutoff/SLA times, 1099 shape, Flo consent (legal), invoice auto-import (deferred).
