"""E8-S4 — the daily BILL_DUE + LATE_FEE_WARNING sweep.

Dates are fixed and ``today`` is passed into ``run()`` everywhere except the
two tests that are about the clock itself, so a suite run on any calendar day
exercises the same weekday arithmetic — which matters, because the reminder
window is measured in business days off the rail's initiation date.

2026-08-14 is a Friday and August 2026 has no federal holiday, so it is the
plain case; 2026-08-01 is the overdue fixture, chosen because the 840:13131
policy ($160 after 15 days) expires on 2026-08-16.
"""

import datetime as dt
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.models import Max
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.banking.factories import BankAccountFactory
from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.bills.services import BillOccurrenceService
from apps.common.dates import initiation_date, today_eastern
from apps.common.enums import (
    AutopayMode,
    BillOccurrenceStatus,
    NotificationType,
    PaymentRail,
    PaymentStatus,
)
from apps.notifications.models import Notification, NotificationPreference
from apps.notifications.services import (
    BillStatusNotifierService,
    NotificationDispatchService,
    bill_status_service,
)
from apps.notifications.services.dedupe import dedupe_key
from apps.notifications.tasks import bill_status_notifier
from apps.payments.factories import PaymentFactory
from apps.payments.services.payment_create_service import PaymentCreateService
from apps.payments.services.resolution_service import PaymentResolutionService
from apps.vendors.factories import (
    UserFactory,
    VendorFactory,
    VendorPaymentMethodFactory,
)
from apps.vendors.models import Vendor
from integrations.messaging.base import DeliveryResult

#: Friday, no federal holiday that week. ACH initiates 2026-08-12, so the
#: three-day window opens 2026-08-09; CHECK initiates 2026-08-07, opening
#: 2026-08-04.
DUE = dt.date(2026, 8, 14)

#: The 840:13131 policy. Grace expires DUE_OVERDUE + 15 = 2026-08-16.
DUE_OVERDUE = dt.date(2026, 8, 1)
LATE_FEE_AMOUNT = Decimal("160.00")
GRACE_DAYS = 15

_PROVIDER = "apps.notifications.tasks.get_messaging_provider"


class SpyMessagingProvider:
    """Records every send instead of delivering one."""

    name = "spy"

    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)

        return DeliveryResult(delivered=True, provider_reference="SPY-1")


class NotifierTestCase(TestCase):
    """Fixture builders shared by every case below."""

    def setUp(self):
        self.user = UserFactory()
        self.service = BillStatusNotifierService()

    def make_vendor(self, *, late_fee_amount=None, late_fee_grace_days=None):
        return VendorFactory(
            user=self.user,
            late_fee_amount=late_fee_amount,
            late_fee_grace_days=late_fee_grace_days,
        )

    def make_occurrence(
        self,
        *,
        due_date=DUE,
        vendor=None,
        autopay_mode=AutopayMode.REMIND,
        rail_trait=None,
        amount="3200.00",
    ):
        """One bill with one occurrence, wired to a stored payment method.

        ``rail_trait`` is a VendorPaymentMethodFactory trait name ("check",
        "network"); the default is the ACH method the factory builds.
        """
        vendor = vendor or self.make_vendor()
        method = VendorPaymentMethodFactory(
            vendor=vendor, **({rail_trait: True} if rail_trait else {})
        )
        bill = BillFactory(
            user=self.user,
            vendor=vendor,
            autopay_mode=autopay_mode,
            payment_method=method,
            amount=amount,
        )

        return BillOccurrenceFactory(
            bill=bill, due_date=due_date, amount=amount
        )

    def late_fee_occurrence(self, **kwargs):
        """The WeWork case: $160 after 15 days, occurrence already overdue."""
        kwargs.setdefault("due_date", DUE_OVERDUE)
        kwargs.setdefault(
            "vendor",
            self.make_vendor(
                late_fee_amount=LATE_FEE_AMOUNT,
                late_fee_grace_days=GRACE_DAYS,
            ),
        )

        return self.make_occurrence(**kwargs)

    def notifications(self, notification_type):
        return Notification.objects.filter(type=notification_type)


class DedupeTests(NotifierTestCase):

    def test_no_second_notification_on_a_rerun_the_same_day(self):
        occurrence = self.make_occurrence()

        first = self.service.run(today=dt.date(2026, 8, 10))
        second = self.service.run(today=dt.date(2026, 8, 10))

        self.assertEqual(first["bill_due"], 1)
        self.assertEqual(second["bill_due"], 0)
        self.assertEqual(second["skipped_duplicate"], 1)
        self.assertEqual(
            self.notifications(NotificationType.BILL_DUE).count(), 1
        )
        self.assertEqual(
            Notification.objects.get().dedupe_key,
            f"{NotificationType.BILL_DUE}:{occurrence.id}:2026-08-10",
        )

    def test_a_key_written_by_a_racing_runner_is_absorbed(self):
        """The constraint is the guarantee; the pre-read is only a shortcut.

        Simulating the pre-read losing the race is the only way to reach the
        IntegrityError branch, which is the branch that actually holds AC1
        when two runners overlap.
        """
        occurrence = self.make_occurrence()
        key = f"{NotificationType.BILL_DUE}:{occurrence.id}:2026-08-10"

        Notification.objects.create(
            user=self.user,
            title="Already sent",
            message="Written by the runner that got there first.",
            type=NotificationType.BILL_DUE,
            dedupe_key=key,
        )

        with mock.patch.object(
            BillStatusNotifierService, "already_sent", return_value=set()
        ):
            report = self.service.run(today=dt.date(2026, 8, 10))

        self.assertEqual(report["skipped_duplicate"], 1)
        self.assertEqual(report["bill_due"], 0)
        self.assertEqual(report["failed"], 0)
        self.assertEqual(Notification.objects.count(), 1)

    def test_duplicate_dedupe_keys_are_rejected_by_the_database(self):
        def create(dedupe_key):
            return Notification.objects.create(
                user=self.user,
                title="Verizon is due",
                message="Approve it to pay.",
                type=NotificationType.BILL_DUE,
                dedupe_key=dedupe_key,
            )

        create("BILL_DUE:x:2026-08-10")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                create("BILL_DUE:x:2026-08-10")

        # NULLs must not collide, or every event-driven notification would be
        # unique-per-database rather than unique-per-schedule.
        create(None)
        create(None)

        self.assertEqual(
            Notification.objects.filter(dedupe_key__isnull=True).count(), 2
        )

    def test_the_dedupe_date_is_eastern_not_utc(self):
        """An evening replay reuses the morning's key, not a fresh one."""
        occurrence = self.make_occurrence()
        evening = dt.datetime(2026, 8, 11, 1, 0, tzinfo=dt.timezone.utc)

        with mock.patch.object(timezone, "now", return_value=evening):
            key = dedupe_key(NotificationType.BILL_DUE, occurrence.id)

            self.assertEqual(timezone.localdate(), dt.date(2026, 8, 11))
            self.assertEqual(today_eastern(), dt.date(2026, 8, 10))

        self.assertTrue(key.endswith(":2026-08-10"))

    def test_run_pins_one_eastern_date_for_the_whole_run(self):
        """A run straddling Eastern midnight cannot re-send its own head."""
        for offset in range(3):
            self.make_occurrence(due_date=DUE + dt.timedelta(days=offset))

        clock = mock.Mock(
            side_effect=[
                dt.date(2026, 8, 10),
                dt.date(2026, 8, 11),
                dt.date(2026, 8, 12),
                dt.date(2026, 8, 13),
            ]
        )

        with mock.patch.object(bill_status_service, "today_eastern", clock):
            report = self.service.run()

        self.assertEqual(clock.call_count, 1)
        self.assertEqual(report["bill_due"], 3)
        self.assertEqual(
            {
                key.rsplit(":", 1)[1]
                for key in Notification.objects.values_list(
                    "dedupe_key", flat=True
                )
            },
            {"2026-08-10"},
        )

    def test_both_types_can_fire_for_one_occurrence_on_one_day(self):
        """The type is part of the key: both are allowed, neither repeats."""
        occurrence = self.late_fee_occurrence()

        first = self.service.run(today=dt.date(2026, 8, 9))
        second = self.service.run(today=dt.date(2026, 8, 9))

        self.assertEqual(first["bill_due"], 1)
        self.assertEqual(first["late_fee"], 1)
        self.assertEqual(second["bill_due"], 0)
        self.assertEqual(second["late_fee"], 0)
        self.assertEqual(second["skipped_duplicate"], 2)

        self.assertEqual(
            set(Notification.objects.values_list("dedupe_key", flat=True)),
            {
                f"{NotificationType.BILL_DUE}:{occurrence.id}:2026-08-09",
                f"{NotificationType.LATE_FEE_WARNING}:{occurrence.id}"
                ":2026-08-09",
            },
        )

    def test_in_app_off_leaves_no_key_and_the_email_flag_is_what_covers_it(
        self,
    ):
        """The known hole in AC1, pinned rather than papered over.

        The key rides on the in-app row, so a user who switched in_app off has
        no row and no key — and the sweep re-emits every day. That is safe
        only while NOTIFICATION_EMAIL_ENABLED is off, because then nothing is
        delivered at all. The second half of this test is what that flag would
        cost: two identical emails for one occurrence on one Eastern day. A
        NotificationDispatch ledger is the precondition for turning it on.
        """
        self.assertFalse(settings.NOTIFICATION_EMAIL_ENABLED)

        self.make_occurrence()
        NotificationPreference.objects.create(
            user=self.user,
            type=NotificationType.BILL_DUE,
            in_app=False,
            email=True,
        )

        provider = SpyMessagingProvider()

        with mock.patch(_PROVIDER, return_value=provider):
            with self.captureOnCommitCallbacks(execute=True):
                self.service.run(today=dt.date(2026, 8, 10))
                self.service.run(today=dt.date(2026, 8, 10))

        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(provider.messages, [])

        with override_settings(NOTIFICATION_EMAIL_ENABLED=True):
            with mock.patch(_PROVIDER, return_value=provider):
                with self.captureOnCommitCallbacks(execute=True):
                    self.service.run(today=dt.date(2026, 8, 11))
                    self.service.run(today=dt.date(2026, 8, 11))

        self.assertEqual(len(provider.messages), 2)
        self.assertEqual(Notification.objects.count(), 0)


class SilenceTests(NotifierTestCase):

    def test_occurrence_with_a_scheduled_payment_is_silent(self):
        for status in (
            PaymentStatus.SCHEDULED,
            PaymentStatus.PENDING,
            PaymentStatus.PROCESSING,
        ):
            with self.subTest(status=status):
                Notification.objects.all().delete()
                occurrence = self.make_occurrence()
                PaymentFactory(
                    user=self.user,
                    vendor=occurrence.bill.vendor,
                    bill_occurrence=occurrence,
                    status=status,
                )

                report = self.service.run(today=dt.date(2026, 8, 10))

                self.assertEqual(report["bill_due"], 0)
                self.assertEqual(report["skipped_live_payment"], 1)
                self.assertEqual(Notification.objects.count(), 0)

                occurrence.bill.delete()

    def test_occurrence_with_a_successful_payment_is_silent(self):
        """SUCCESSFUL is in the silence set, carried over verbatim."""
        occurrence = self.make_occurrence()
        PaymentFactory(
            user=self.user,
            vendor=occurrence.bill.vendor,
            bill_occurrence=occurrence,
            status=PaymentStatus.SUCCESSFUL,
        )

        report = self.service.run(today=dt.date(2026, 8, 10))

        self.assertEqual(report["skipped_live_payment"], 1)
        self.assertEqual(Notification.objects.count(), 0)

    def test_occurrence_with_a_failed_payment_still_notifies(self):
        """A failed payment buys no silence — the 840:13131 scenario."""
        occurrence = self.make_occurrence()
        PaymentFactory(
            user=self.user,
            vendor=occurrence.bill.vendor,
            bill_occurrence=occurrence,
            status=PaymentStatus.FAILED,
        )
        occurrence.status = BillOccurrenceStatus.UPCOMING
        occurrence.save(update_fields=["status"])

        report = self.service.run(today=dt.date(2026, 8, 10))

        self.assertEqual(report["bill_due"], 1)
        self.assertEqual(report["skipped_live_payment"], 0)

    def test_occurrence_marked_paid_by_hand_is_silent(self):
        """mark_as_paid writes no Payment row, so only the status filter
        catches it."""
        occurrence = self.make_occurrence()
        BillOccurrenceService().mark_as_paid(occurrence, "SWP-manual")

        report = self.service.run(today=dt.date(2026, 8, 10))

        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(report["skipped_live_payment"], 0)

    def test_approval_marking_the_occurrence_scheduled_stops_reminders(self):
        """The E6-S9 loop end to end: remind, approve, stop reminding."""
        occurrence = self.make_occurrence()
        BankAccountFactory(connection__user=self.user)

        first = self.service.run(today=dt.date(2026, 8, 10))

        PaymentCreateService().create(
            user=self.user,
            occurrence_ids=[occurrence.id],
            rail=PaymentRail.ACH_STANDARD,
            today=dt.date(2026, 8, 10),
        )

        occurrence.refresh_from_db()
        second = self.service.run(today=dt.date(2026, 8, 11))

        self.assertEqual(first["bill_due"], 1)
        self.assertEqual(occurrence.status, BillOccurrenceStatus.SCHEDULED)
        self.assertEqual(second["bill_due"], 0)
        self.assertEqual(
            self.notifications(NotificationType.BILL_DUE).count(), 1
        )

    def test_deleted_bill_is_skipped(self):
        occurrence = self.make_occurrence()
        occurrence.bill.deleted_at = timezone.now()
        occurrence.bill.save(update_fields=["deleted_at"])

        report = self.service.run(today=dt.date(2026, 8, 10))

        self.assertEqual(report["bill_due"], 0)
        self.assertEqual(Notification.objects.count(), 0)


class BillDueWindowTests(NotifierTestCase):

    def test_remind_bill_is_reminded_before_the_ach_initiation_date(self):
        self.make_occurrence()

        # Provenance of the window, spelled out rather than assumed.
        self.assertEqual(
            initiation_date(DUE, PaymentRail.ACH_STANDARD),
            dt.date(2026, 8, 12),
        )

        early = self.service.run(today=dt.date(2026, 8, 8))
        opening = self.service.run(today=dt.date(2026, 8, 9))

        self.assertEqual(early["bill_due"], 0)
        self.assertEqual(opening["bill_due"], 1)

    def test_check_bill_opens_its_window_earlier_than_an_ach_bill(self):
        self.make_occurrence()
        check_occurrence = self.make_occurrence(rail_trait="check")

        self.assertEqual(
            initiation_date(DUE, PaymentRail.CHECK), dt.date(2026, 8, 7)
        )

        report = self.service.run(today=dt.date(2026, 8, 4))

        self.assertEqual(report["bill_due"], 1)
        self.assertEqual(
            Notification.objects.get().metadata["occurrence_id"],
            str(check_occurrence.id),
        )

    def test_reminders_stop_after_the_overdue_tail(self):
        """30 days: a monthly bill's reminders stop as the next cycle's
        begin, so an abandoned occurrence cannot stack them forever."""
        self.make_occurrence()

        last = self.service.run(today=DUE + dt.timedelta(days=30))
        past = self.service.run(today=DUE + dt.timedelta(days=31))

        self.assertEqual(last["bill_due"], 1)
        self.assertEqual(past["bill_due"], 0)

    def test_auto_bill_gets_no_bill_due_reminder(self):
        self.make_occurrence(autopay_mode=AutopayMode.AUTO)

        report = self.service.run(today=dt.date(2026, 8, 10))

        self.assertEqual(report["bill_due"], 0)
        self.assertEqual(Notification.objects.count(), 0)

    def test_bill_due_payload_carries_the_approval_deep_link(self):
        occurrence = self.make_occurrence()

        self.service.run(today=dt.date(2026, 8, 10))

        notification = Notification.objects.get()
        self.assertEqual(
            notification.metadata["bill_id"], str(occurrence.bill_id)
        )
        self.assertEqual(
            notification.metadata["occurrence_id"], str(occurrence.id)
        )
        self.assertEqual(notification.metadata["due_date"], "2026-08-14")
        self.assertEqual(
            notification.title,
            f"{occurrence.bill.vendor.name} is due",
        )


class LateFeeWarningTests(NotifierTestCase):

    def test_late_fee_warning_fires_exactly_at_the_threshold(self):
        occurrence = self.late_fee_occurrence()

        quiet = self.service.run(today=dt.date(2026, 8, 8))
        warned = self.service.run(today=dt.date(2026, 8, 9))

        self.assertEqual(quiet["late_fee"], 0)
        self.assertEqual(warned["late_fee"], 1)

        notification = self.notifications(
            NotificationType.LATE_FEE_WARNING
        ).get()
        self.assertEqual(notification.metadata["days_remaining"], 7)
        self.assertEqual(notification.metadata["late_fee_amount"], "160.00")
        self.assertEqual(notification.metadata["grace_days"], GRACE_DAYS)
        self.assertEqual(
            notification.metadata["occurrence_id"], str(occurrence.id)
        )

    def test_last_day_of_grace_still_warns(self):
        occurrence = self.late_fee_occurrence()

        report = self.service.run(today=dt.date(2026, 8, 16))

        self.assertEqual(report["late_fee"], 1)
        self.assertEqual(
            self.notifications(NotificationType.LATE_FEE_WARNING)
            .get()
            .metadata["days_remaining"],
            0,
        )

        # E6-S6 agrees the fee has not applied yet on that same day.
        block = PaymentResolutionService()._late_fee(
            occurrence.bill.vendor, days_overdue=15
        )
        self.assertFalse(block["applies"])
        self.assertEqual(block["days_remaining"], 0)

    def test_after_the_grace_period_it_is_too_late_to_warn(self):
        self.late_fee_occurrence()

        for offset in range(0, 8):
            day = dt.date(2026, 8, 17) + dt.timedelta(days=offset)

            with self.subTest(today=day):
                self.assertEqual(self.service.run(today=day)["late_fee"], 0)

        self.assertEqual(
            self.notifications(NotificationType.LATE_FEE_WARNING).count(), 0
        )

    def test_vendor_without_a_late_fee_policy_is_never_warned(self):
        self.make_occurrence(due_date=DUE_OVERDUE)

        for offset in range(-30, 31):
            self.service.run(today=DUE_OVERDUE + dt.timedelta(days=offset))

        self.assertEqual(
            self.notifications(NotificationType.LATE_FEE_WARNING).count(), 0
        )

    def test_vendor_with_a_zero_late_fee_is_never_warned(self):
        vendor = self.make_vendor(
            late_fee_amount=Decimal("0.00"), late_fee_grace_days=10
        )
        self.make_occurrence(due_date=DUE_OVERDUE, vendor=vendor)

        for offset in range(0, 12):
            self.service.run(today=DUE_OVERDUE + dt.timedelta(days=offset))

        self.assertEqual(
            self.notifications(NotificationType.LATE_FEE_WARNING).count(), 0
        )

    def test_vendor_with_a_fee_and_no_grace_days_warns_on_the_due_date(self):
        vendor = self.make_vendor(
            late_fee_amount=LATE_FEE_AMOUNT, late_fee_grace_days=None
        )
        self.make_occurrence(due_date=DUE_OVERDUE, vendor=vendor)

        on_time = self.service.run(today=DUE_OVERDUE)
        late = self.service.run(today=DUE_OVERDUE + dt.timedelta(days=1))

        self.assertEqual(on_time["late_fee"], 1)
        self.assertEqual(late["late_fee"], 0)
        self.assertEqual(
            self.notifications(NotificationType.LATE_FEE_WARNING)
            .get()
            .metadata["days_remaining"],
            0,
        )

    def test_auto_bill_still_gets_a_late_fee_warning(self):
        """"As any user", not "as a REMIND user": AUTO goes overdue too."""
        self.late_fee_occurrence(autopay_mode=AutopayMode.AUTO)

        report = self.service.run(today=dt.date(2026, 8, 9))

        self.assertEqual(report["late_fee"], 1)
        self.assertEqual(report["bill_due"], 0)

    def test_long_grace_period_is_not_dropped_by_the_overdue_floor(self):
        """A 45-day grace is still counting down 40 days past the due date."""
        today = dt.date(2026, 9, 20)
        vendor = self.make_vendor(
            late_fee_amount=LATE_FEE_AMOUNT, late_fee_grace_days=45
        )
        self.make_occurrence(
            due_date=today - dt.timedelta(days=40), vendor=vendor
        )

        self.assertEqual(
            self.service.window_floor(today), today - dt.timedelta(days=45)
        )

        report = self.service.run(today=today)

        self.assertEqual(report["late_fee"], 1)
        self.assertEqual(report["bill_due"], 0)
        self.assertEqual(
            self.notifications(NotificationType.LATE_FEE_WARNING)
            .get()
            .metadata["days_remaining"],
            5,
        )


class ReportTests(NotifierTestCase):
    """The report is the job's only operational signal, so it has to be true.

    ``notify()`` does not raise when every channel is off for a type — it
    returns a result with no notification and nothing handed off. The counter
    used to be incremented regardless, so the nightly log and the task's
    return value over-reported for exactly the users the known dedupe hole
    covers, night after night.
    """

    def mute(self, *, in_app=False, email=False):
        return NotificationPreference.objects.create(
            user=self.user,
            type=NotificationType.BILL_DUE,
            in_app=in_app,
            email=email,
        )

    def test_an_emission_no_channel_accepted_is_not_counted_as_a_send(self):
        self.make_occurrence()
        self.mute()

        report = self.service.run(today=dt.date(2026, 8, 10))

        self.assertEqual(report["bill_due"], 0)
        self.assertEqual(report["skipped_no_channel"], 1)
        self.assertEqual(report["failed"], 0)
        self.assertEqual(Notification.objects.count(), 0)

    def test_email_wanted_but_flagged_off_is_not_a_send_either(self):
        """Which is what makes the in_app-off dedupe hole harmless today.

        With ``NOTIFICATION_EMAIL_ENABLED`` off, a user who wants email and
        not in-app receives nothing at all, so re-evaluating the occurrence
        tomorrow delivers nothing twice — and the report says so out loud
        instead of claiming a send.
        """
        self.assertFalse(settings.NOTIFICATION_EMAIL_ENABLED)

        self.make_occurrence()
        self.mute(email=True)

        provider = SpyMessagingProvider()

        with mock.patch(_PROVIDER, return_value=provider):
            with self.captureOnCommitCallbacks(execute=True):
                report = self.service.run(today=dt.date(2026, 8, 10))

        self.assertEqual(report["bill_due"], 0)
        self.assertEqual(report["skipped_no_channel"], 1)
        self.assertEqual(provider.messages, [])
        self.assertEqual(Notification.objects.count(), 0)

    def test_an_email_only_delivery_does_still_count_as_a_send(self):
        """The counter must not under-report either.

        No in-app row means no dedupe key — that is the hole DedupeTests
        pins — but an email genuinely went out, so it is a send and the
        number has to say so.
        """
        self.make_occurrence()
        self.mute(email=True)

        provider = SpyMessagingProvider()

        with override_settings(NOTIFICATION_EMAIL_ENABLED=True):
            with mock.patch(_PROVIDER, return_value=provider):
                with self.captureOnCommitCallbacks(execute=True):
                    report = self.service.run(today=dt.date(2026, 8, 10))

        self.assertEqual(report["bill_due"], 1)
        self.assertEqual(report["skipped_no_channel"], 0)
        self.assertEqual(len(provider.messages), 1)
        self.assertEqual(Notification.objects.count(), 0)

    def test_the_task_returns_the_number_of_rows_it_actually_wrote(self):
        """The send count the beat log and every operator reads."""
        self.make_occurrence(due_date=today_eastern())
        self.mute()

        self.assertEqual(bill_status_notifier.apply().get(), 0)
        self.assertEqual(Notification.objects.count(), 0)


class ResilienceTests(NotifierTestCase):

    def test_a_failure_midway_leaves_earlier_notifications_and_the_rerun_finishes_the_job(
        self,
    ):
        for offset in range(3):
            self.make_occurrence(due_date=DUE + dt.timedelta(days=offset))

        real_notify = NotificationDispatchService.notify
        calls = []

        def flaky(dispatcher, **kwargs):
            calls.append(1)

            if len(calls) == 2:
                raise RuntimeError("the second row blew up")

            return real_notify(dispatcher, **kwargs)

        with mock.patch.object(
            NotificationDispatchService, "notify", flaky
        ):
            with self.assertLogs(
                "apps.notifications.services.bill_status_service",
                level="ERROR",
            ):
                first = self.service.run(today=dt.date(2026, 8, 10))

        self.assertEqual(first["bill_due"], 2)
        self.assertEqual(first["failed"], 1)
        self.assertEqual(Notification.objects.count(), 2)

        second = self.service.run(today=dt.date(2026, 8, 10))

        self.assertEqual(second["bill_due"], 1)
        self.assertEqual(second["skipped_duplicate"], 2)
        self.assertEqual(Notification.objects.count(), 3)
        self.assertEqual(
            Notification.objects.values("dedupe_key").distinct().count(), 3
        )

    def test_a_classification_failure_does_not_abandon_the_rest_of_the_run(
        self,
    ):
        """Only emission used to be guarded, and that was not enough.

        ``types_for`` reads the vendor's late-fee policy and the bill's rail,
        so it fails on bad data the same way emission does — a non-finite
        Decimal in ``late_fee_amount``, a rail with no lead-time entry. It sat
        outside the try, so one unusable row took every occurrence queued
        behind it down with it and ``run()`` returned no report at all, which
        the task would then have met with a KeyError.
        """
        occurrences = [
            self.make_occurrence(due_date=DUE + dt.timedelta(days=offset))
            for offset in range(3)
        ]
        doomed = occurrences[1]
        real_types_for = BillStatusNotifierService.types_for

        def flaky(service, occurrence, today):
            if occurrence.id == doomed.id:
                raise ValueError("unclassifiable")

            return real_types_for(service, occurrence, today)

        with mock.patch.object(
            BillStatusNotifierService, "types_for", flaky
        ):
            with self.assertLogs(
                "apps.notifications.services.bill_status_service",
                level="ERROR",
            ):
                report = self.service.run(today=dt.date(2026, 8, 10))

        self.assertEqual(report["bill_due"], 2)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(Notification.objects.count(), 2)
        self.assertNotIn(
            str(doomed.id),
            [
                notification.metadata["occurrence_id"]
                for notification in Notification.objects.all()
            ],
        )

    def test_the_candidate_query_does_not_scale_with_occurrence_count(self):
        """Fixed cost stays fixed; per-row cost stays at one insert's worth.

        The four fixed queries are the grace aggregate, the candidate read,
        the live-payment ids and the dedupe pre-read. The three per-emission
        queries are the savepoint, the insert and the savepoint release — no
        ``.exists()`` per occurrence, which is what the old ReminderService
        did, and no preference read per occurrence either: the run holds one
        NotificationDispatchService, which resolves each (user, type) once.

        The fifth query is that single preference read. It is written as
        ``one_preference_read`` rather than folded into ``fixed`` so that
        reintroducing a per-row lookup moves the number by N, not by one.
        """
        fixed = 4
        one_preference_read = 1
        per_emission = 3

        for _ in range(10):
            self.make_occurrence()

        with CaptureQueriesContext(connection) as small:
            self.service.run(today=dt.date(2026, 8, 10))

        for _ in range(40):
            self.make_occurrence()

        with CaptureQueriesContext(connection) as large:
            self.service.run(today=dt.date(2026, 8, 11))

        self.assertEqual(
            len(small), fixed + one_preference_read + 10 * per_emission
        )
        self.assertEqual(
            len(large), fixed + one_preference_read + 50 * per_emission
        )

        self.assertEqual(
            len(
                [
                    query
                    for query in large.captured_queries
                    if "notification_preferences" in query["sql"]
                ]
            ),
            one_preference_read,
        )

    def test_one_users_preferences_are_read_once_however_many_bills(self):
        """The read that used to repeat per emission, pinned by itself.

        Fifty occurrences for one user is fifty BILL_DUE emissions and one
        preference row. Asserting the SELECT count directly means a
        regression here fails on a number that says what it is, rather than
        on an arithmetic identity in the budget test above.
        """
        for _ in range(50):
            self.make_occurrence()

        with CaptureQueriesContext(connection) as ctx:
            report = self.service.run(today=dt.date(2026, 8, 10))

        preference_reads = [
            query
            for query in ctx.captured_queries
            if "notification_preferences" in query["sql"]
        ]

        self.assertEqual(report["bill_due"], 50)
        self.assertEqual(len(preference_reads), 1)

    def test_a_second_user_costs_one_more_preference_read_not_zero(self):
        """The memo is per (user, type), not a process-wide cache.

        Worth pinning: a cache that answered for the wrong user would be a
        privacy bug, not a performance win, and it would look identical in
        the budget test.
        """
        self.make_occurrence()

        other = UserFactory()
        vendor = VendorFactory(user=other)
        method = VendorPaymentMethodFactory(vendor=vendor)
        bill = BillFactory(
            user=other,
            vendor=vendor,
            autopay_mode=AutopayMode.REMIND,
            payment_method=method,
            amount="90.00",
        )
        BillOccurrenceFactory(bill=bill, due_date=DUE, amount="90.00")

        NotificationPreference.objects.create(
            user=other,
            type=NotificationType.BILL_DUE,
            in_app=False,
            email=False,
        )

        with CaptureQueriesContext(connection) as ctx:
            report = self.service.run(today=dt.date(2026, 8, 10))

        preference_reads = [
            query
            for query in ctx.captured_queries
            if "notification_preferences" in query["sql"]
        ]

        self.assertEqual(len(preference_reads), 2)
        # The second user's preferences were honoured, not the first's.
        self.assertEqual(report["bill_due"], 1)
        self.assertEqual(report["skipped_no_channel"], 1)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(Notification.objects.get().user_id, self.user.id)


class WiringTests(NotifierTestCase):

    def test_beat_entry_runs_at_five_eastern(self):
        entry = settings.CELERY_BEAT_SCHEDULE[
            "notifications-bill-status-notifier"
        ]

        self.assertEqual(entry["task"], "notifications.bill_status_notifier")
        self.assertEqual(entry["schedule"].hour, {5})
        self.assertEqual(entry["schedule"].minute, {0})
        self.assertEqual(settings.CELERY_TIMEZONE, "America/New_York")

        # Ordered after the jobs whose output it reads: a reminder for an
        # occurrence that already has money moving is what this buys.
        release = settings.CELERY_BEAT_SCHEDULE["payments-release-scheduled"][
            "schedule"
        ]
        self.assertGreater(
            min(entry["schedule"].hour) * 60 + min(entry["schedule"].minute),
            min(release.hour) * 60 + min(release.minute),
        )

    def test_task_is_registered_and_returns_the_send_count(self):
        """Derived from today_eastern(), so this stays calendar-proof."""
        today = today_eastern()
        self.make_occurrence(due_date=today)

        self.assertEqual(bill_status_notifier.apply().get(), 1)
        self.assertEqual(
            self.notifications(NotificationType.BILL_DUE).count(), 1
        )

    def test_the_dedupe_constraint_exists_on_the_model(self):
        names = {
            constraint.name
            for constraint in Notification._meta.constraints
        }

        self.assertIn("uniq_notification_dedupe_key", names)
        # The indexes E8-S3 shipped are untouched by the Meta edit.
        self.assertEqual(
            [index.fields for index in Notification._meta.indexes],
            [["user"], ["is_read"], ["created_at"], ["type"]],
        )

    def test_window_floor_reads_the_longest_grace_period_in_use(self):
        self.make_vendor(
            late_fee_amount=LATE_FEE_AMOUNT, late_fee_grace_days=90
        )
        self.make_vendor(
            late_fee_amount=LATE_FEE_AMOUNT, late_fee_grace_days=5
        )

        self.assertEqual(
            Vendor.objects.aggregate(longest=Max("late_fee_grace_days"))[
                "longest"
            ],
            90,
        )
        self.assertEqual(
            self.service.window_floor(DUE), DUE - dt.timedelta(days=90)
        )
