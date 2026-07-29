"""Daily reminder + late-fee countdown (E8-S4).

The single producer of "this bill needs you". It replaces the unwired
``ReminderService`` that lived in ``apps/payments/services/autopay_service.py``
and emits two types:

* ``BILL_DUE``         — REMIND bills inside the approval window (834:3436)
* ``LATE_FEE_WARNING`` — any bill racing its vendor's grace period (840:13131)

PAYMENT_FAILED / PAYMENT_ARRIVED are webhook-driven (E6-S8) and are not this
job's business.

Every date comes from ``today_eastern()``. ``timezone.localdate()`` follows
``TIME_ZONE`` = UTC, so it rolls over at 19:00/20:00 ET and would key part of
the year's dedupe rows to the wrong calendar day.

Idempotency lives on ``Notification.dedupe_key``, which means it lives on the
in-app row — and a user who has switched in_app off for a type has no row and
therefore no key. That is deliberate rather than overlooked: honouring the
preference is E8-S3's contract, and with ``NOTIFICATION_EMAIL_ENABLED`` off
such a user receives nothing at all, so re-evaluating the occurrence tomorrow
delivers nothing twice. A NotificationDispatch ledger is the hard precondition
for ever turning that flag on — see the setting's own comment. The run report
counts those emissions as ``skipped_no_channel`` rather than as sends, so the
size of that population is visible in the nightly log instead of inflating it.
"""

import datetime as dt
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max

from apps.bills.models.bill_occurrence import BillOccurrence
from apps.bills.selectors.occurrence_status import open_occurrences
from apps.common.dates import initiation_date, today_eastern
from apps.common.enums import AutopayMode, NotificationType
from apps.notifications.channels import PENDING_COMMIT, SENT
from apps.notifications.models import Notification
from apps.notifications.services import NotificationDispatchService
from apps.notifications.services.dedupe import dedupe_key
from apps.payments.selectors.live_payments import (
    occurrence_ids_with_live_payment,
)

# The module, not the name: autopay_service imports notify() from this very
# package, so binding ``rail_for_bill`` here would fail whenever payments was
# the module loaded first. Resolving the attribute at call time breaks the
# cycle without hiding the dependency in a function body.
from apps.payments.services import autopay_service
from apps.vendors.models import Vendor
from apps.vendors.services.late_fee import days_until_late_fee, grace_days

logger = logging.getLogger(__name__)

_RELATED = ("bill", "bill__user", "bill__vendor", "bill__payment_method")

#: Calendar-day padding for the coarse SQL window. The longest rail lead is 5
#: business days (CHECK, apps/common/dates.py RAIL_LEAD_BUSINESS_DAYS); across
#: a holiday week that is at most ~10 calendar days, so 12 is a safe upper
#: bound. The exact per-rail test runs in Python.
_MAX_LEAD_CALENDAR_DAYS = 12

#: SQLite caps bound parameters; chunk the dedupe pre-read rather than
#: building one IN () of every key in the run.
_KEY_CHUNK = 1000

#: The outcomes that mean something actually left this service: a durable
#: in-app row, or a hand-off that fires on commit. Everything else — skipped
#: by preference, disabled by config, unsupported, failed — wrote nothing and
#: delivered nothing, so the report must not call it a send.
_DELIVERED_OUTCOMES = (SENT, PENDING_COMMIT)


class BillStatusNotifierService:

    def __init__(self):
        self.lead_days = settings.BILL_DUE_REMINDER_LEAD_DAYS
        self.overdue_days = settings.BILL_DUE_REMINDER_OVERDUE_DAYS
        self.late_fee_threshold = settings.LATE_FEE_WARNING_THRESHOLD_DAYS

    # --- entry point ------------------------------------------------------

    def run(self, today=None):
        """Emit today's reminders. Idempotent within one Eastern day.

        Deliberately not wrapped in a single transaction: a crash at row 500
        of 1000 must leave the first 499 sent and committed, and the re-run
        must pick up at 500 rather than re-sending the lot.
        """
        # Pinned once. A run that straddles Eastern midnight has to key every
        # row it writes to the same day, or its tail re-sends its head.
        today = today or today_eastern()

        occurrences = list(self.candidates(today))
        silenced = occurrence_ids_with_live_payment(
            [occurrence.id for occurrence in occurrences]
        )
        pending = [
            occurrence
            for occurrence in occurrences
            if occurrence.id not in silenced
        ]

        report = {
            "bill_due": 0,
            "late_fee": 0,
            "skipped_live_payment": len(occurrences) - len(pending),
            "skipped_duplicate": 0,
            "skipped_no_channel": 0,
            "failed": 0,
        }

        counter = {
            NotificationType.BILL_DUE: "bill_due",
            NotificationType.LATE_FEE_WARNING: "late_fee",
        }

        # One dispatcher for the whole run. It memoises the preference row it
        # resolves per (user, type), so a user with twenty bills costs one
        # SELECT against notification_preferences rather than twenty. Built
        # here rather than in __init__ because that memo is a snapshot and
        # must not outlive the run that took it.
        dispatcher = NotificationDispatchService()

        already_sent = self.already_sent(pending, today)

        for occurrence in pending:
            try:
                types = self.types_for(occurrence, today)
            except Exception:
                # Classification reads the vendor's late-fee policy and the
                # bill's rail, so it can fail on bad data exactly the way
                # emission can. Guarded for the same reason: one unusable row
                # must not abandon every occurrence queued behind it.
                report["failed"] += 1
                logger.exception(
                    "bill_status_notifier could not classify occurrence %s",
                    occurrence.pk,
                )
                continue

            for notification_type in types:
                key = dedupe_key(notification_type, occurrence.id, today)

                if key in already_sent:
                    report["skipped_duplicate"] += 1
                    continue

                try:
                    result = self.emit(
                        dispatcher, occurrence, notification_type, key, today
                    )
                except IntegrityError:
                    # Another runner — a second beat, a manual replay — won
                    # the race on this key. That is the constraint doing its
                    # job, not a failure.
                    report["skipped_duplicate"] += 1
                except Exception:
                    # One bad row must not end the run.
                    report["failed"] += 1
                    logger.exception(
                        "bill_status_notifier failed for occurrence %s",
                        occurrence.pk,
                    )
                else:
                    # notify() does not raise when every channel is off for
                    # this type — it returns a result with no notification and
                    # nothing handed off. Counting that as a send would have
                    # the task's only operational signal over-report for
                    # exactly the users the dedupe hole covers, every night.
                    report[
                        counter[notification_type]
                        if self.delivered(result)
                        else "skipped_no_channel"
                    ] += 1

        logger.info("bill_status_notifier %s", report)

        return report

    @staticmethod
    def delivered(result):
        """Whether this emission produced a row or a hand-off."""
        return any(
            outcome in _DELIVERED_OUTCOMES
            for outcome in result.outcomes.values()
        )

    # --- selection --------------------------------------------------------

    def candidates(self, today):
        """Every open occurrence either arm could speak about today.

        One query, coarse by design: the BILL_DUE window depends on the bill's
        rail and the late-fee window on the vendor's grace period, neither of
        which is worth expressing in SQL. ``open_occurrences`` (E4-S1) drops
        SCHEDULED/PAID rows, which is what catches a bill marked paid by hand —
        ``BillOccurrenceService.mark_as_paid`` writes no Payment row, so the
        payment filter alone would keep nagging it.
        """
        ceiling = today + dt.timedelta(
            days=max(
                self.lead_days + _MAX_LEAD_CALENDAR_DAYS,
                self.late_fee_threshold,
            )
        )

        return (
            open_occurrences(
                BillOccurrence.objects.filter(
                    bill__deleted_at__isnull=True,
                    due_date__gte=self.window_floor(today),
                    due_date__lte=ceiling,
                )
            )
            .select_related(*_RELATED)
            .order_by("due_date")
        )

    def window_floor(self, today):
        """How far back the SQL window has to reach.

        BILL_DUE stops ``overdue_days`` past the due date, but a late-fee
        countdown runs on the *vendor's* clock: a 45-day grace period is still
        counting down 40 days after the due date. Reading the longest grace
        period actually in use costs one aggregate and is the only floor that
        cannot silently drop a warning.
        """
        longest_grace = (
            Vendor.objects.aggregate(longest=Max("late_fee_grace_days"))[
                "longest"
            ]
            or 0
        )

        return today - dt.timedelta(
            days=max(self.overdue_days, longest_grace)
        )

    def types_for(self, occurrence, today):
        types = []

        if self.is_due_reminder(occurrence, today):
            types.append(NotificationType.BILL_DUE)

        if self.is_late_fee_warning(occurrence, today):
            types.append(NotificationType.LATE_FEE_WARNING)

        return types

    def is_due_reminder(self, occurrence, today):
        """REMIND-mode only, windowed off the rail's initiation date.

        A REMIND user's approval is what starts the payment (E6-S9), so the
        reminder has to arrive before the money must *leave*, not before the
        due date: ACH_STANDARD initiates 2 business days early and CHECK 5.
        Reminding on the due date — what the old ReminderService did — is
        already too late to pay on time.

        AUTO bills are excluded: they pay themselves, and an AUTO bill whose
        authorization is dead already gets its own alert from AutopayService.
        """
        if occurrence.bill.autopay_mode != AutopayMode.REMIND:
            return False

        rail = autopay_service.rail_for_bill(occurrence.bill)

        opens = initiation_date(occurrence.due_date, rail) - dt.timedelta(
            days=self.lead_days
        )
        closes = occurrence.due_date + dt.timedelta(days=self.overdue_days)

        return opens <= today <= closes

    def is_late_fee_warning(self, occurrence, today):
        """Any autopay mode: an AUTO bill whose payment failed is overdue too.

        ``days_until_late_fee`` is None when the vendor has no policy, and
        negative once the fee has already applied. A *warning* about a fee that
        has already landed is a lie; that state belongs to the failure screen
        (E6-S6 ``late_fee.applies``), not to a countdown.
        """
        remaining = self.days_remaining(occurrence, today)

        if remaining is None:
            return False

        return 0 <= remaining <= self.late_fee_threshold

    def days_remaining(self, occurrence, today):
        return days_until_late_fee(
            due_date=occurrence.due_date,
            vendor=occurrence.bill.vendor,
            today=today,
        )

    # --- emission ---------------------------------------------------------

    def already_sent(self, occurrences, today):
        """Keys written earlier today, in one query per chunk.

        The unique constraint is what makes a duplicate impossible; this read
        is what makes the common case — a re-run after a crash — cheap, rather
        than N IntegrityErrors and N savepoint rollbacks.
        """
        keys = [
            dedupe_key(notification_type, occurrence.id, today)
            for occurrence in occurrences
            for notification_type in (
                NotificationType.BILL_DUE,
                NotificationType.LATE_FEE_WARNING,
            )
        ]

        sent = set()

        for start in range(0, len(keys), _KEY_CHUNK):
            sent.update(
                Notification.objects.filter(
                    dedupe_key__in=keys[start:start + _KEY_CHUNK]
                ).values_list("dedupe_key", flat=True)
            )

        return sent

    def emit(self, dispatcher, occurrence, notification_type, key, today):
        """One notification, inside its own savepoint.

        The savepoint is not optional: on Postgres an IntegrityError poisons
        the surrounding transaction, so catching it without one would break
        every write that follows in the same run.

        ``dispatcher`` is the run's single ``NotificationDispatchService``
        rather than the module-level ``notify()`` every event-driven caller
        uses — same code path, but one instance means one preference read per
        (user, type) instead of one per emission.
        """
        with transaction.atomic():
            return dispatcher.notify(
                user=occurrence.bill.user,
                type=notification_type,
                context=self.context(occurrence, notification_type, today),
                dedupe_key=key,
            )

    def context(self, occurrence, notification_type, today):
        """Deep-link payload. Approval calls E6-S2 with these ids."""
        bill = occurrence.bill
        vendor = bill.vendor

        context = {
            "bill_id": str(bill.id),
            "occurrence_id": str(occurrence.id),
            "vendor_name": vendor.name,
            "amount": str(occurrence.amount),
            "due_date": occurrence.due_date.isoformat(),
        }

        if notification_type == NotificationType.LATE_FEE_WARNING:
            context["late_fee_amount"] = str(vendor.late_fee_amount)
            context["grace_days"] = grace_days(vendor)
            context["days_remaining"] = self.days_remaining(occurrence, today)

        return context
