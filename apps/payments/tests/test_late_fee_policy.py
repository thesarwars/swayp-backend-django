"""E8-S4 — one definition of "has a late-fee policy", for E6-S6 and E8-S4.

The failure screen (`GET payments/<id>/failure/`) and the warning job answer
the same two questions — is there a policy, and how long is left — so they now
answer them from the same module. These tests pin the one deliberate change
that fell out of that (a $0.00 fee is no policy) and the absence of any other.
"""

import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.common.dates import add_business_days, is_business_day
from apps.common.enums import AutopayMode, NotificationType, PaymentStatus
from apps.notifications.models import Notification
from apps.notifications.services import BillStatusNotifierService
from apps.payments.factories import PaymentFactory
from apps.payments.services.resolution_service import PaymentResolutionService
from apps.vendors.factories import (
    UserFactory,
    VendorFactory,
    VendorPaymentMethodFactory,
)
from apps.vendors.services.late_fee import (
    days_until_late_fee,
    grace_days,
    has_late_fee_policy,
)


class LateFeePolicyTests(TestCase):

    def setUp(self):
        self.service = PaymentResolutionService()
        self.vendor = VendorFactory(
            late_fee_amount=Decimal("160.00"), late_fee_grace_days=15
        )

    def test_zero_late_fee_returns_no_block_from_the_failure_endpoint(self):
        """"$0.00 late fee in 3 days" is not a warning, so it is no policy."""
        free = VendorFactory(
            late_fee_amount=Decimal("0.00"), late_fee_grace_days=10
        )

        self.assertFalse(has_late_fee_policy(free))
        self.assertIsNone(grace_days(free))
        self.assertIsNone(self.service._late_fee(free, days_overdue=3))
        self.assertIsNone(self.service._late_fee(None, days_overdue=3))
        self.assertIsNone(
            self.service._late_fee(VendorFactory(), days_overdue=3)
        )

        # Everything else about the shipped block is unchanged.
        self.assertEqual(
            self.service._late_fee(self.vendor, days_overdue=8),
            {
                "amount": Decimal("160.00"),
                "grace_days": 15,
                "days_remaining": 7,
                "applies": False,
            },
        )

    def test_days_until_late_fee_matches_the_e6_s6_countdown(self):
        """`grace - days_overdue` and `(due + grace) - today` are one sum."""
        due = dt.date(2026, 8, 1)

        for days_overdue in range(0, 31):
            with self.subTest(days_overdue=days_overdue):
                remaining = days_until_late_fee(
                    due_date=due,
                    vendor=self.vendor,
                    today=due + dt.timedelta(days=days_overdue),
                )
                block = self.service._late_fee(self.vendor, days_overdue)

                self.assertEqual(remaining, 15 - days_overdue)
                self.assertEqual(max(remaining, 0), block["days_remaining"])
                self.assertEqual(block["applies"], remaining < 0)

    def test_a_vendor_with_a_fee_and_no_grace_days_has_a_zero_day_grace(self):
        vendor = VendorFactory(
            late_fee_amount=Decimal("25.00"), late_fee_grace_days=None
        )
        due = dt.date(2026, 8, 1)

        self.assertEqual(grace_days(vendor), 0)
        self.assertEqual(
            days_until_late_fee(due_date=due, vendor=vendor, today=due), 0
        )
        self.assertEqual(
            days_until_late_fee(
                due_date=due,
                vendor=vendor,
                today=due + dt.timedelta(days=1),
            ),
            -1,
        )

    def test_late_fee_uses_calendar_days_not_business_days(self):
        """The epic's "date engine" reading, asserted rather than assumed.

        A late fee is a contractual term on the vendor's calendar, so a five
        day grace from a Friday expires on Veterans Day — a bank holiday the
        transit engine would have skipped straight past.
        """
        due = dt.date(2026, 11, 6)
        veterans_day = dt.date(2026, 11, 11)
        vendor = VendorFactory(
            late_fee_amount=Decimal("160.00"), late_fee_grace_days=5
        )

        self.assertFalse(is_business_day(veterans_day))
        self.assertEqual(add_business_days(due, 5), dt.date(2026, 11, 16))

        self.assertEqual(
            days_until_late_fee(
                due_date=due, vendor=vendor, today=veterans_day
            ),
            0,
        )
        self.assertEqual(
            days_until_late_fee(
                due_date=due,
                vendor=vendor,
                today=veterans_day + dt.timedelta(days=1),
            ),
            -1,
        )

    def test_the_default_today_is_eastern_not_utc(self):
        """Without it the last day of grace becomes the first day of the
        fee at 20:00 Eastern — when a countdown is most likely to be read."""
        evening = dt.datetime(2026, 8, 17, 1, 0, tzinfo=dt.timezone.utc)

        with mock.patch.object(timezone, "now", return_value=evening):
            self.assertEqual(timezone.localdate(), dt.date(2026, 8, 17))
            self.assertEqual(
                days_until_late_fee(
                    due_date=dt.date(2026, 8, 1), vendor=self.vendor
                ),
                0,
            )


class LateFeeSurfacesAgreeTests(TestCase):
    """Sharing the arithmetic is worth nothing if the surfaces disagree on
    the day.

    ``failure()`` derived ``days_overdue`` from ``timezone.localdate()``,
    which is UTC and rolls over at 19:00/20:00 ET, while the E8-S4 job is
    Eastern by construction. For the four to five hours between them the two
    screens made opposite claims about the same $160.
    """

    #: 21:00 America/New_York on 2026-08-16 — the last day of a 15-day grace
    #: period on an occurrence due 2026-08-01, and already the next day in
    #: UTC. The whole disagreement lives in this one instant.
    EVENING = dt.datetime(2026, 8, 17, 1, 0, tzinfo=dt.timezone.utc)

    def setUp(self):
        self.user = UserFactory()
        self.vendor = VendorFactory(
            user=self.user,
            late_fee_amount=Decimal("160.00"),
            late_fee_grace_days=15,
        )
        bill = BillFactory(
            user=self.user,
            vendor=self.vendor,
            autopay_mode=AutopayMode.REMIND,
            payment_method=VendorPaymentMethodFactory(vendor=self.vendor),
            amount="3200.00",
        )
        self.occurrence = BillOccurrenceFactory(
            bill=bill, due_date=dt.date(2026, 8, 1), amount="3200.00"
        )
        self.payment = PaymentFactory(
            user=self.user,
            vendor=self.vendor,
            bill_occurrence=self.occurrence,
            status=PaymentStatus.FAILED,
        )

    def test_the_failure_screen_reads_the_same_day_as_the_warning_job(self):
        with mock.patch.object(timezone, "now", return_value=self.EVENING):
            self.assertEqual(timezone.localdate(), dt.date(2026, 8, 17))

            detail = PaymentResolutionService().failure(
                user=self.user, payment_id=self.payment.id
            )
            report = BillStatusNotifierService().run()

        # The screen: fifteen days overdue, last day of grace, no fee yet.
        self.assertEqual(detail["days_overdue"], 15)
        self.assertEqual(
            detail["late_fee"],
            {
                "amount": Decimal("160.00"),
                "grace_days": 15,
                "days_remaining": 0,
                "applies": False,
            },
        )

        # The job, in the same instant, on the same occurrence: still
        # counting down, and keyed to the Eastern day the screen just used.
        self.assertEqual(report["late_fee"], 1)

        warning = Notification.objects.get(
            type=NotificationType.LATE_FEE_WARNING
        )
        self.assertEqual(warning.metadata["days_remaining"], 0)
        self.assertTrue(warning.dedupe_key.endswith(":2026-08-16"))

    def test_the_fee_lands_on_both_surfaces_on_the_same_next_day(self):
        """The boundary itself, one Eastern day later."""
        next_evening = self.EVENING + dt.timedelta(days=1)

        with mock.patch.object(timezone, "now", return_value=next_evening):
            detail = PaymentResolutionService().failure(
                user=self.user, payment_id=self.payment.id
            )
            report = BillStatusNotifierService().run()

        self.assertEqual(detail["days_overdue"], 16)
        self.assertTrue(detail["late_fee"]["applies"])
        # A warning about a fee that has already landed is a lie, so the job
        # goes quiet exactly where the screen flips.
        self.assertEqual(report["late_fee"], 0)
