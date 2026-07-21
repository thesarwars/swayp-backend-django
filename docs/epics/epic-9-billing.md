# E9 — Billing & Subscriptions

**Goal:** the commercial layer from BRD §6.2 — subscription plans, per-plan allowances, per-transaction fees + overages, **auto-refunds when a delivery guarantee is missed**, and Enterprise add-ons as separate invoiceable line items.
**Release:** R2 · **Blocked by:** E1 · **New app:** `apps/billing` · **Screens:** none provided (settings/billing UI missing — PRD §10-Q8)

> **Source of truth:** BRD §6.2 "Commercial Pricing Structure — RESOLVED" + "Engineering impact". Numbers are fixed by the CEO; do not invent.

**Plan reference (BRD §6.2):**
| Plan | Price | Seats | Banks | Checks/mo free | Notable |
|---|---|---|---|---|---|
| Founding | $49/mo (price-locked, first 500) | 3 | 1 | 2 | unlimited bills/vendors, full Flo |
| Standard | $99/mo | 10 | unlimited | 5 | 1099 reporting, priority support |
| Enterprise | custom (base $299 + add-ons) | **unlimited** | unlimited | (Standard incl.) | multi-entity, workflows, ERP, SLA |

**Per-transaction (BRD §6.2):** standard ACH free/unlimited · same-day ACH **$4.99** (opt-in, **unbilled after the daily bank cutoff**) · standard check **2 free (Founding) / 5 free (Standard) then $2.99** · expedited check **$8.99** (all plans).

---

## E9-S1 · Plan + Subscription models

**ORM (`apps/billing/models/`):**
```python
class Plan(BaseModel):
    code            = CharField(max_length=20, unique=True)     # FOUNDING | STANDARD | ENTERPRISE
    name            = CharField(max_length=50)
    monthly_price   = DecimalField(18, 2)                       # 49.00 / 99.00 / 299.00 (ent base)
    seat_limit      = PositiveIntegerField(null=True)           # 3 / 10 / null=unlimited
    bank_limit      = PositiveIntegerField(null=True)           # 1 / null=unlimited
    free_checks_per_month = PositiveIntegerField(default=0)     # 2 / 5 / (per contract)
    included_entities = PositiveIntegerField(default=1)         # ent: 3
    price_locked    = BooleanField(default=False)               # Founding first-500
    class Meta: db_table = "plans"

class Subscription(BaseModel):
    account       = FK("users.User", CASCADE, related_name="subscriptions")  # or Account/Org owner
    plan          = FK(Plan, PROTECT, related_name="subscriptions")
    status        = CharField(choices=[ACTIVE, PAST_DUE, CANCELLED], default=ACTIVE)
    period_start  = DateField(); period_end = DateField()
    locked_price  = DecimalField(18, 2, null=True)             # honors Founding price-lock
    class Meta: db_table = "subscriptions"; indexes = [account, status]
```
**AC:** [ ] Founding price-lock respected on renewal; [ ] plan seed migration with the exact BRD numbers; [ ] one active subscription per account (constraint)

## E9-S2 · Allowance counters (per customer per cycle)

**As** the platform **I need** per-cycle allowance tracking **so that** free checks/seats/banks are enforced and overages bill correctly.

**ORM:**
```python
class AllowanceCounter(BaseModel):
    subscription = FK(Subscription, CASCADE, related_name="counters")
    kind         = CharField(choices=[CHECKS, SEATS, BANKS])   # metered vs capacity
    period_start = DateField()
    used         = PositiveIntegerField(default=0)
    class Meta:
        db_table = "allowance_counters"
        constraints = [UniqueConstraint(fields=["subscription","kind","period_start"], name="uniq_counter")]
```
**Behavior:** capacity kinds (seats/banks) checked at add-time (E10 seat add, E5 bank connect) → 402/403 when over plan limit; metered kind (checks) increments on each check send (E6 check path) and flips to overage once free allotment consumed.
**AC:** [ ] check counter resets per billing cycle; [ ] bank connect (E5) blocked past `bank_limit`; [ ] seat add (E10) blocked past `seat_limit`; [ ] concurrency-safe increment (select_for_update)

## E9-S3 · Per-transaction fee billing

**As** the platform **I need** to bill same-day ACH + check fees correctly **so that** revenue and allowances reconcile.

**ORM (`FeeCharge` ledger):**
```python
class FeeCharge(BaseModel):
    subscription = FK(Subscription, PROTECT, related_name="fee_charges")
    payment      = FK("payments.Payment", PROTECT, related_name="fee_charges")
    kind         = CharField(choices=[SAME_DAY_ACH, EXPEDITED_CHECK, CHECK_OVERAGE])
    amount       = DecimalField(18, 2)                # 4.99 / 8.99 / 2.99
    state        = CharField(choices=[PENDING, BILLED, REFUNDED], default=PENDING)
    class Meta: db_table = "fee_charges"; indexes = [subscription, payment, state]
```
**Rules (BRD §6.2):** same-day ACH $4.99 charged **only if** requested **before** the daily bank cutoff (E1-S5 calendar) — after cutoff, same-day is not offered and **no FeeCharge is created**; expedited check $8.99 always; standard check $2.99 **only after** the free allotment (E9-S2) is exhausted.
**AC:** [ ] no same-day fee row when booked after cutoff; [ ] check overage charged only past the free count; [ ] fee rows link to the Payment; [ ] amounts exactly $4.99 / $8.99 / $2.99

## E9-S4 · Delivery-guarantee auto-refunds

**As a** customer **I'm auto-refunded** the same-day-ACH or expedited-check fee **when Swayp misses the delivery guarantee** (BRD §6.2 engineering impact).

**Behavior:** on each `FeeCharge` for SAME_DAY_ACH / EXPEDITED_CHECK, record the **guaranteed arrival date** (E1-S5). A reconciliation job (or the E6 webhook consumer) compares actual arrival vs guarantee; if missed → transition FeeCharge → REFUNDED and emit a notification. The exact SLA per rail is PRD §10-Q9.
**AC:** [ ] missed-guarantee fixture → fee auto-refunded + customer notified; [ ] met-guarantee → no refund; [ ] refund is idempotent (one refund per fee); [ ] success metric "100% of missed guarantees refunded" measurable from the ledger

## E9-S5 · Enterprise add-on line items

**As** finance **I need** Enterprise add-ons as **separate, trackable, invoiceable** items (BRD §6.2) — not one opaque "custom" charge.

**ORM:**
```python
class EnterpriseAddOn(BaseModel):
    subscription = FK(Subscription, CASCADE, related_name="addons")
    kind         = CharField(choices=[EXTRA_ENTITY, APPROVAL_WORKFLOW, ERP_SYNC, CUSTOM_SLA])
    quantity     = PositiveIntegerField(default=1)             # e.g. entities beyond 3
    unit_price   = DecimalField(18, 2)                         # 79 / 99 / 149 / 199
    class Meta: db_table = "enterprise_addons"
```
**Rates (BRD §6.2):** base **$299** (incl. up to 3 entities) · **+$79/entity** beyond 3 · **+$99** approval workflow · **+$149** ERP sync · **+$199** custom SLA. Extra-entity add-on is billed only for entity count > 3 (ties to E10 entities).
**AC:** [ ] invoice preview lists each add-on as its own line with correct unit price; [ ] entity add-on count = max(0, entities − 3); [ ] toggling an add-on updates the invoice deterministically

---

## Cross-epic hooks
- **E5** (bank connect) checks `bank_limit` before creating a `BankConnection`.
- **E6** (payments): check send increments the CHECK counter (E9-S2) and creates `FeeCharge` (E9-S3); same-day ACH eligibility uses the cutoff calendar; missed guarantees feed E9-S4.
- **E10** (teams) checks `seat_limit` before adding a member; entity count drives E9-S5.
- **E8** reports gate 1099 on plan (Standard+).

## Open questions (billing)
- Payment rails **for the subscription itself** (does Swayp charge the customer's card via Stripe Billing?) — not specified in the BRD; confirm (Stripe Billing is a natural fit and is not an excluded competitor).
- Exact per-rail **delivery-guarantee SLA** that triggers refunds (PRD §10-Q9).
- Proration on plan change / mid-cycle upgrades — confirm policy.
