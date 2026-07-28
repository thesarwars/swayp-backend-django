import datetime as dt

from django.test import SimpleTestCase

from apps.common.enums import BillFrequency, PaymentRail
from apps.common import dates


class BusinessDayTests(SimpleTestCase):

    def test_friday_plus_one_is_monday(self):
        friday = dt.date(2026, 1, 9)  # Friday
        self.assertEqual(friday.weekday(), 4)
        self.assertEqual(
            dates.add_business_days(friday, 1),
            dt.date(2026, 1, 12),  # Monday
        )

    def test_holiday_is_skipped(self):
        # 2025-07-04 (Independence Day) is a Friday; Thu +1 biz day -> Mon 7th.
        thursday = dt.date(2025, 7, 3)
        self.assertFalse(dates.is_business_day(dt.date(2025, 7, 4)))
        self.assertEqual(
            dates.add_business_days(thursday, 1),
            dt.date(2025, 7, 7),
        )

    def test_sunday_christmas_observed_monday(self):
        # 2022-12-25 is a Sunday -> observed Monday 2022-12-26.
        self.assertFalse(dates.is_business_day(dt.date(2022, 12, 26)))
        self.assertIn(
            dt.date(2022, 12, 26),
            dates.us_federal_holidays(2022),
        )

    def test_saturday_holiday_not_shifted_to_friday(self):
        # 2026-07-04 is a Saturday; the Fed does NOT close the preceding Friday.
        self.assertTrue(dates.is_business_day(dt.date(2026, 7, 3)))

    def test_negative_business_days(self):
        # Independence week 2025: Mon 7th - 1 biz day skips weekend + Fri holiday.
        monday = dt.date(2025, 7, 7)
        self.assertEqual(
            dates.add_business_days(monday, -1),
            dt.date(2025, 7, 3),
        )


class MonthClampTests(SimpleTestCase):

    def test_clamp_feb_nonleap(self):
        self.assertEqual(
            dates.clamp_to_month(2023, 2, 31),
            dt.date(2023, 2, 28),
        )

    def test_clamp_feb_leap(self):
        self.assertEqual(
            dates.clamp_to_month(2024, 2, 31),
            dt.date(2024, 2, 29),
        )

    def test_add_months_clamps(self):
        self.assertEqual(
            dates.add_months(dt.date(2024, 1, 31), 1),
            dt.date(2024, 2, 29),
        )
        self.assertEqual(
            dates.add_months(dt.date(2024, 12, 15), 1),
            dt.date(2025, 1, 15),
        )


class RecurrenceTests(SimpleTestCase):

    def test_monthly_next_after_anchor(self):
        anchor = dt.date(2026, 1, 31)
        self.assertEqual(
            dates.next_occurrence(
                anchor, BillFrequency.MONTHLY, after=anchor
            ),
            dt.date(2026, 2, 28),
        )

    def test_quarterly(self):
        anchor = dt.date(2026, 1, 15)
        self.assertEqual(
            dates.next_occurrence(
                anchor, BillFrequency.QUARTERLY, after=anchor
            ),
            dt.date(2026, 4, 15),
        )

    def test_weekly_keeps_weekday(self):
        anchor = dt.date(2026, 1, 5)  # Monday
        nxt = dates.next_occurrence(
            anchor, BillFrequency.WEEKLY, after=anchor
        )
        self.assertEqual(nxt, dt.date(2026, 1, 12))
        self.assertEqual(nxt.weekday(), anchor.weekday())

    def test_one_time(self):
        anchor = dt.date(2026, 3, 1)
        self.assertEqual(
            dates.next_occurrence(anchor, BillFrequency.ONE_TIME),
            anchor,
        )


class RailLeadTests(SimpleTestCase):

    def test_ach_standard_initiates_two_business_days_early(self):
        due = dt.date(2026, 1, 15)  # Thursday
        self.assertEqual(
            dates.initiation_date(due, PaymentRail.ACH_STANDARD),
            dt.date(2026, 1, 13),  # Tuesday
        )

    def test_estimated_arrival_ach_standard(self):
        sent = dt.date(2026, 1, 13)  # Tuesday
        self.assertEqual(
            dates.estimated_arrival(sent, PaymentRail.ACH_STANDARD),
            dt.date(2026, 1, 15),
        )

    def test_network_same_or_next_day(self):
        sent = dt.date(2026, 1, 13)
        self.assertEqual(
            dates.estimated_arrival(sent, PaymentRail.NETWORK),
            dt.date(2026, 1, 14),
        )


class DstCutoffTests(SimpleTestCase):

    def test_est_offset_in_winter(self):
        cutoff = dates.cutoff_datetime_et(dt.date(2026, 1, 15))
        self.assertEqual(
            cutoff.utcoffset(), dt.timedelta(hours=-5)
        )

    def test_edt_offset_in_summer(self):
        cutoff = dates.cutoff_datetime_et(dt.date(2026, 7, 15))
        self.assertEqual(
            cutoff.utcoffset(), dt.timedelta(hours=-4)
        )
