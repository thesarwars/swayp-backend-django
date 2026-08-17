# Swayp Backend — File Architecture

**Status:** Convention in force (established with the `authentication` refactor, commit `00a6b9a`).
**Rule:** *No monolithic `serializers.py` / `views.py` / `urls.py`. Every app exposes per-feature packages — file names describe the feature, not the layer.* Example: registration code lives in `serializers/user_registration.py`, `views/user_registration.py`, `urls/user_registration.py`.

---

## 1. Project layout

```
backend/
├── manage.py
├── requirements.txt
├── config/                          # project plumbing only
│   ├── settings/
│   │   ├── base.py                  # shared settings
│   │   ├── local.py                 # dev (DJANGO_SETTINGS_MODULE default)
│   │   ├── production.py
│   │   └── test.py
│   ├── urls.py                      # admin, schema/docs, api/v1 mount, webhooks mount (versionless)
│   ├── celery.py                    # ← PLANNED (E1-S1): Celery app + beat
│   ├── asgi.py / wsgi.py
├── api/
│   └── v1/
│       └── urls.py                  # THE v1 manifest — one include() per app prefix
├── integrations/                    # ← PLANNED: provider interfaces (plain package, not a Django app)
│   ├── bank_data/    base.py · mock.py · plaid.py
│   ├── money_movement/ base.py · mock.py · stripe.py · moov.py    # Stripe=configured-account, Moov=ACH (BRD §5)
│   ├── directory/    base.py · mock.py
│   ├── check_mail/   base.py · mock.py · lob.py
│   └── llm/          base.py · template.py · anthropic.py
├── apps/                            # one Django app per bounded context
└── docs/                            # planning docs (gitignored)
    ├── PRD.md · dashboard-plan.md · file-architecture.md · figma_node.md
    ├── third-party-services-and-production-requirements.md
    └── epics/                       # backlog: one file per epic
```

### URL mounting rules
- `config/urls.py` mounts **only**: `admin/`, `api/schema|docs|redoc/`, `api/v1/` → `api.v1.urls`, and (planned) `webhooks/` → versionless, because processor-registered URLs must never move with API versions.
- `api/v1/urls.py` holds exactly one `include()` per app prefix. Nothing else.
- Each app's `urls/__init__.py` aggregates its feature url modules (see template).

## 2. Canonical app template

`authentication` is the reference implementation. Every app converges on:

```
apps/<app>/
├── __init__.py · apps.py · admin.py
├── api/
│   ├── __init__.py
│   ├── serializers/
│   │   ├── __init__.py              # re-exports every serializer (stable import path)
│   │   └── <feature>.py             # e.g. user_registration.py, password_reset.py
│   ├── views/
│   │   ├── __init__.py              # re-exports every view
│   │   └── <feature>.py             # thin: validate → call service → respond
│   └── urls/
│       ├── __init__.py              # urlpatterns = [*<feature>_urls, ...]
│       └── <feature>.py             # named routes for that feature only
├── models/
│   ├── __init__.py                  # re-exports every model
│   └── <entity>.py                  # one file per entity (users/ already does this)
├── services/
│   └── <feature>_service.py         # business logic; the only layer that writes via repositories
├── selectors/
│   └── <feature>_selector.py        # read-side queries (annotations, aggregates)
├── repositories.py                  # persistence writes
├── schemas.py                       # drf-spectacular helpers (if needed)
├── migrations/
└── tests/
    ├── __init__.py
    └── test_<feature>.py            # mirrors feature names
```

### Layer rules
| Layer | May import | Never |
|---|---|---|
| `views/<feature>.py` | its feature serializer, its service | models directly, other apps' services |
| `serializers/` | models (read), enums | services |
| `services/` | repositories, selectors, `integrations/` interfaces | views, serializers |
| `selectors/` | models | anything that writes |
| `integrations/` impls | third-party SDKs | Django models (pass plain data in/out) |

### Naming rules
- Feature file names are **domain-first**: `user_registration.py`, `user_login.py`, `otp.py`, `password_reset.py`, `token.py` — not `serializers2.py`, not layer names.
- URL route `name=` uses kebab-case matching the path (`verify-otp`).
- Views end in `View`/`APIView`; new money-facing views subclass `BaseAPIView` (`apps/common/base_views.py`) with `service_class`; webhooks subclass the planned `WebhookAPIView` (unauthenticated, signature-verified).
- Enums live in `apps/common/enums.py` **except** app-local ones that predate this rule (`OTPPurpose` in `apps/authentication/models/otp.py` — keep, do not duplicate).

## 3. Current state per app (2026-07-16)

| App | api/ feature packages | models/ package | services/ · selectors/ | Action |
|---|---|---|---|---|
| `authentication` | ✅ done (reference) | ✅ (`otp.py`, …) | services ✅ / no selectors (OK — no reads) | conform tests next |
| `users` | n/a (no endpoints) | ✅ per-entity | — | none |
| `payments` | ❌ flat files at app root | ❌ `models.py` | ✅ both | migrate when E6 touches it |
| `providers`, `wallet`, `dashboard`, `notifications`, `payment_tracking`, `bill_categories` | ❌ flat | ❌ | partial | migrate opportunistically (when an epic touches the app) |
| `common` | — | ✅ `models/base.py` | — | add `providers`? No — integrations live top-level |

**Migration policy:** don't do a big-bang rewrite. Whichever epic first touches an app converts it to the template in the same PR (the change is mechanical: split by feature, add re-exporting `__init__.py`s, keep route names).

## 4. Planned new apps (from dashboard-plan.md)

| App | Feature files (api/serializers|views|urls) | Entities (models/) |
|---|---|---|
| `banking` | `link.py`, `accounts.py`, `scan.py`, `onboarding.py`, `routing.py` | `bank_connection.py`, `bank_account.py`, `transaction_scan.py`, `bill_detection_candidate.py` |
| `vendors` | `vendor.py`, `payment_methods.py`, `directory.py`, `qr.py` | `vendor.py`, `vendor_payment_method.py` |
| `bills` | `bill.py`, `occurrences.py`, `wizard.py`, `qr.py`, `invoice.py` | `bill.py`, `bill_occurrence.py`, `standing_authorization.py` |
| `payments` (extend) | `create.py`, `confirm.py`, `status.py`, `resolution.py`, `history.py` | `payment.py`, `payment_batch.py`, `payment_stage.py`, `payment_authorization.py`, `webhook_event.py`, `idempotency_key.py` |
| `ai_advisor` | `cash_context.py`, `projection.py`, `consent.py` | `advisor_consent.py` |
| `reports` | `reports.py` | — (query-time) |
| `billing` (E9) | `plans.py`, `subscription.py`, `allowances.py`, `fees.py`, `addons.py` | `plan.py`, `subscription.py`, `allowance_counter.py`, `fee_charge.py`, `enterprise_addon.py` |
| `teams` (E10) | `members.py`, `invitations.py`, `entities.py` | `team_member.py`, `entity.py` |
| `webhooks` | `plaid.py`, `moov.py`, `stripe.py`, `lob.py` (urls mounted at `/webhooks`, versionless) | — (uses `payments.WebhookEvent`) |

`api/v1/urls.py` gains: `/banking`, `/vendors`, `/bills`, `/ai`, `/reports`, `/billing`, `/teams`. `config/urls.py` gains: `webhooks`. Provider `integrations/money_movement/` = `stripe.py` + `moov.py` (BRD §5); `check_mail/` = `lob.py`/`postgrid.py`. **No `dwolla.py`/`gocardless.py`.**

## 5. Worked example (authentication — as shipped)

```
apps/authentication/api/
├── serializers/
│   ├── __init__.py            # re-exports every serializer
│   ├── user_registration.py   # RegisterSerializer
│   ├── user_login.py          # LoginSerializer
│   ├── otp.py                 # Resend/VerifyOTPSerializer
│   ├── password_reset.py      # Forgot/Reset(+Verify)PasswordSerializer
│   └── token.py               # RefreshSerializer, LogoutSerializer
├── views/                     # same five feature files
└── urls/                      # same five feature files; __init__ aggregates:
                               # register, login, verify-otp,
                               # resend-otp, refresh, logout,
                               # forgot-password, reset-password
```

Verified: `manage.py check` clean · every route reverses · the OpenAPI schema emits every auth path.
