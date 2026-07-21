# E8 — Dashboard, Reports & Notifications

**Goal:** the home aggregate, the reports page, and out-of-app notification plumbing (types, preferences, reminder jobs).
**Release:** S1 in R1 · S2–S3 in R2 · S4 in R3 · **Blocked by:** E3+E4 (S1), E6 (S4)
**Screens:** 565:4649, 666:5374, 834:3436 (remind mode), 840:12632 ("Resolve Failed" entry)

---

## E8-S1 · Home dashboard aggregate — `GET dashboard/home/`

**As a** user **I land on** "Welcome Back, Jhon" with stats, recent bills, vendors preview, and the right-rail pay panel with Overdue/Due/Upcoming tab counts (565:4649).

**Response (one round-trip):**
```jsonc
{
  "greeting": {"name": "Jhon"},
  "stats": {"due_this_month": "18450.00", "total_bills": 6, "paid": 3},
  "recent_bills": [{vendor, logo, amount, due_date, status}],          // top 3–5 occurrences
  "vendors_preview": [{name, logo, category, monthly_amount, rail}],   // top 3
  "pay_panel": {
    "tabs": {"overdue": 14, "due": 9, "upcoming": 14},                 // occurrence counts (E4 model resolves 6-vs-14)
    "items": [{vendor, amount, due_date, status}]                      // active tab preloaded
  }
}
```
Extends `apps/dashboard` (migrate app to feature packages in same PR: `api/views/home.py`, …).
**AC:**
- [ ] Selector-composed (no N+1; assert query count)
- [ ] Numbers reconcile with `bills/summary/` + `vendors/summary/` under same user fixture
- [ ] p95 ≤ 500 ms on seeded volume (1k occurrences)

## E8-S2 · Reports — `GET reports/?vendor=<id>&date_from=&date_to=`

**As a** user **I filter** payments by vendor and date range (666:5374).

**New app `apps/reports`** — query-time aggregation over payments/occurrences: rows (date, vendor, bill, amount, rail, status) + totals block. Output columns/export **TBD** (PRD §10-Q4) — build the JSON table now, leave an `export=` hook unimplemented (405 "not yet supported") rather than guessing CSV/PDF. ⟳ **1099 reporting** is a Standard-plan feature (BRD §6.2) — gate the 1099 report/data view on the customer's plan (E9); form-generation-vs-export shape is PRD §10-Q4.
**AC:**
- [ ] Paginated; both filters optional; empty state defined
- [ ] Totals match payment history sums (property test on fixtures)
- [ ] 1099 report available on Standard+ only (plan-gated); 403/empty on Founding

## E8-S3 · Notification types + preferences

**As a** user **I control** which alerts reach me per channel; **as** flows **we emit** typed events.

**ORM:** extend enums + new model:
```python
NotificationType += BILL_DUE, PAYMENT_FAILED, PAYMENT_REVERSED, AUTOPAY_EXECUTED, PAYMENT_ARRIVED, LATE_FEE_WARNING

class NotificationPreference(BaseModel):      # apps/notifications/models/notification_preference.py
    user  = FK(settings.AUTH_USER_MODEL, CASCADE, related_name="notification_preferences")
    type  = CharField(max_length=30, choices=NotificationType.choices)
    in_app = BooleanField(default=True); email = BooleanField(default=True)
    sms   = BooleanField(default=False); push = BooleanField(default=False)   # ⟳ email + in-app only this release (BRD §1.2); SMS/push columns reserved, no delivery adapters yet
    class Meta:
        db_table = "notification_preferences"
        constraints = [UniqueConstraint(fields=["user", "type"], name="uniq_pref_per_type")]
```
**API:** `GET/PATCH notifications/preferences/` (upsert per type). Emission helper: `notify(user, type, context)` checks prefs → in-app row (exists today) + channel tasks. ⟳ **This release ships email + in-app only (BRD §1.2 — SMS/push deferred);** channel adapters sit behind an interface, external delivery flagged until R4. Payloads carry deep-link context (`bill_id`, `occurrence_id`, `payment_id`).
*(Settings screen assumed — PRD §10-Q12.)*
**AC:**
- [ ] Defaults created lazily; PATCH validates known types
- [ ] `notify()` respects prefs (matrix test)
- [ ] Migrate `apps/notifications` to feature packages in same PR

## E8-S4 · Reminder + late-fee jobs (Celery `bill_status_notifier`)

**As a** REMIND-mode user **I get** "approve this payment" before due date (834:3436); **as any** user **I get** failure alerts and "no late fee yet — N days left" countdowns (840:13131).

**Work:** daily NY-timezone beat: BILL_DUE for occurrences due within lead-time window (skips occurrences with live payment — E6-S9 contract); LATE_FEE_WARNING when `due + grace_days − today ≤ threshold` (vendor late-fee fields, E3-S1); PAYMENT_FAILED/PAYMENT_ARRIVED emitted from E6 webhook consumer (not this job).
**AC:**
- [ ] No duplicate reminder per occurrence per day (dedupe key tested)
- [ ] Occurrence with SCHEDULED/live payment → silence (integration test with E6 fixtures)
- [ ] Late-fee math via date engine; vendor without policy → no warning
