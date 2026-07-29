"""Per-method lead time / initiation date (E3-S6)."""

import datetime as dt

from django.test import SimpleTestCase

from apps.common.enums import PaymentRail, VendorPaymentMethodType
from apps.vendors.models import VendorPaymentMethod
from apps.vendors.services.payment_method_schedule import (
    rail_for_method,
    schedule_for_method,
)

D = dt.date


def method(method_type, supports_same_day=False):
    """An unsaved instance — the schedule maths never touches the DB."""
    return VendorPaymentMethod(
        method_type=method_type,
        supports_same_day=supports_same_day,
    )


class RailMappingTests(SimpleTestCase):

    def test_rail_per_method_type(self):
        cases = [
            (method(VendorPaymentMethodType.NETWORK), PaymentRail.NETWORK),
            (method(VendorPaymentMethodType.CHECK), PaymentRail.CHECK),
            (method(VendorPaymentMethodType.ACH), PaymentRail.ACH_STANDARD),
            (
                method(VendorPaymentMethodType.ACH, supports_same_day=True),
                PaymentRail.ACH_SAMEDAY,
            ),
        ]

        for payment_method, expected in cases:
            with self.subTest(rail=expected):
                self.assertEqual(rail_for_method(payment_method), expected)

    def test_unknown_method_type_has_no_rail(self):
        self.assertIsNone(rail_for_method(method("SOMETHING_ELSE")))

    def test_unknown_method_type_yields_no_schedule(self):
        self.assertIsNone(
            schedule_for_method(method("SOMETHING_ELSE"), D(2026, 11, 30))
        )


class ScheduleTests(SimpleTestCase):

    def test_initiation_steps_over_thanksgiving(self):
        """Due Mon 2026-11-30; Thanksgiving falls Thu 2026-11-26."""
        schedule = schedule_for_method(
            method(VendorPaymentMethodType.ACH),
            D(2026, 11, 30),
            today=D(2026, 11, 1),
        )

        # Two business days back: Fri Nov 27, then Thu Nov 26 is a holiday, so
        # the second lands on Wed Nov 25.
        self.assertEqual(schedule["initiate_by"], D(2026, 11, 25))
        self.assertEqual(schedule["lead_business_days"], 2)

    def test_check_lead_crosses_a_weekend_and_a_holiday(self):
        schedule = schedule_for_method(
            method(VendorPaymentMethodType.CHECK),
            D(2026, 11, 30),
            today=D(2026, 11, 1),
        )

        self.assertEqual(schedule["initiate_by"], D(2026, 11, 20))
        self.assertEqual(schedule["lead_business_days"], 5)

    def test_ach_and_check_arrive_on_the_due_date(self):
        """Lead and transit match on these rails, so arrival == due date."""
        for method_type in (
            VendorPaymentMethodType.ACH,
            VendorPaymentMethodType.CHECK,
        ):
            with self.subTest(method_type=method_type):
                schedule = schedule_for_method(
                    method(method_type),
                    D(2026, 11, 30),
                    today=D(2026, 11, 1),
                )
                self.assertEqual(
                    schedule["estimated_arrival"], D(2026, 11, 30)
                )

    def test_initiation_never_lands_on_a_weekend(self):
        # Due Mon 2026-08-03; two business days back crosses the weekend.
        schedule = schedule_for_method(
            method(VendorPaymentMethodType.ACH),
            D(2026, 8, 3),
            today=D(2026, 7, 1),
        )

        self.assertEqual(schedule["initiate_by"], D(2026, 7, 30))
        self.assertLess(schedule["initiate_by"].weekday(), 5)

    def test_can_meet_due_date_is_true_before_the_initiation_date(self):
        schedule = schedule_for_method(
            method(VendorPaymentMethodType.ACH),
            D(2026, 11, 30),
            today=D(2026, 11, 25),
        )

        self.assertTrue(schedule["can_meet_due_date"])

    def test_can_meet_due_date_is_false_once_it_has_passed(self):
        schedule = schedule_for_method(
            method(VendorPaymentMethodType.ACH),
            D(2026, 11, 30),
            today=D(2026, 11, 26),
        )

        self.assertFalse(schedule["can_meet_due_date"])

    def test_same_day_ach_needs_no_lead(self):
        schedule = schedule_for_method(
            method(VendorPaymentMethodType.ACH, supports_same_day=True),
            D(2026, 11, 30),
            today=D(2026, 11, 1),
        )

        self.assertEqual(schedule["rail"], PaymentRail.ACH_SAMEDAY)
        self.assertEqual(schedule["lead_business_days"], 0)
        self.assertEqual(schedule["initiate_by"], D(2026, 11, 30))
