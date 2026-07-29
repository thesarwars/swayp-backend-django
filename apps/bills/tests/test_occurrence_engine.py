"""Occurrence generation + read-time status (E4-S1 / E4-S6)."""

import datetime as dt
from decimal import Decimal

from django.test import TestCase

from apps.bill_categories.models import BillCategory
from apps.bills.models.bill import Bill
from apps.bills.models.bill_occurrence import BillOccurrence
from apps.bills.selectors.bill_occurrence_selector import BillOccurrenceSelector
from apps.bills.selectors.occurrence_status import annotate_status
from apps.bills.services.bill_occurrence_service import BillOccurrenceService
from apps.common.enums import (
    BillFrequency,
    BillOccurrenceStatus,
)
from apps.users.models import User
from apps.vendors.models import Vendor

D = dt.date


class OccurrenceTestCase(TestCase):

    def setUp(self):
        self.service = BillOccurrenceService()
        self.selector = BillOccurrenceSelector()

        self.user = User.objects.create_user(
            email="occurrences@example.com",
            password="Sw@yp-Test-1",
        )
        self.category = BillCategory.objects.create(
            name="Utilities",
            icon="https://example.com/i.png",
            color="#111111",
        )
        self.vendor = Vendor.objects.create(
            user=self.user,
            name="WeWork",
            category=self.category,
        )

    def make_bill(self, anchor, frequency=BillFrequency.MONTHLY, amount="3200.00"):
        return Bill.objects.create(
            user=self.user,
            vendor=self.vendor,
            category=self.category,
            amount=amount,
            frequency=frequency,
            anchor_date=anchor,
        )


class HorizonTests(OccurrenceTestCase):

    def test_future_anchor_starts_at_the_anchor(self):
        bill = self.make_bill(D(2026, 8, 1))

        self.assertEqual(
            self.service.horizon_due_dates(bill, today=D(2026, 7, 28)),
            [D(2026, 8, 1), D(2026, 9, 1), D(2026, 10, 1)],
        )

    def test_past_anchor_starts_at_the_current_period(self):
        """A bill anchored months ago lands on its current unpaid period."""
        bill = self.make_bill(D(2026, 1, 15))

        self.assertEqual(
            self.service.horizon_due_dates(bill, today=D(2026, 7, 28)),
            [D(2026, 7, 15), D(2026, 8, 15), D(2026, 9, 15)],
        )

    def test_anchor_exactly_today(self):
        bill = self.make_bill(D(2026, 7, 28))

        self.assertEqual(
            self.service.horizon_due_dates(bill, today=D(2026, 7, 28)),
            [D(2026, 7, 28), D(2026, 8, 28), D(2026, 9, 28)],
        )

    def test_month_end_horizon_clamps_then_recovers(self):
        bill = self.make_bill(D(2026, 1, 31))

        self.assertEqual(
            self.service.horizon_due_dates(bill, today=D(2026, 2, 10)),
            [D(2026, 1, 31), D(2026, 2, 28), D(2026, 3, 31)],
        )

    def test_one_time_yields_exactly_one_date(self):
        bill = self.make_bill(D(2026, 9, 9), frequency=BillFrequency.ONE_TIME)

        self.assertEqual(
            self.service.horizon_due_dates(bill, today=D(2026, 7, 28)),
            [D(2026, 9, 9)],
        )

    def test_horizon_is_current_period_plus_two_cycles(self):
        bill = self.make_bill(D(2026, 7, 1), frequency=BillFrequency.WEEKLY)

        dates = self.service.horizon_due_dates(bill, today=D(2026, 7, 28))

        self.assertEqual(len(dates), self.service.HORIZON_CYCLES + 1)


class GenerationTests(OccurrenceTestCase):

    def test_generation_creates_the_horizon(self):
        bill = self.make_bill(D(2026, 8, 1))

        created = self.service.generate_occurrences(bill, today=D(2026, 7, 28))

        self.assertEqual(len(created), 3)
        self.assertEqual(
            list(
                bill.occurrences.order_by("due_date").values_list(
                    "due_date", flat=True
                )
            ),
            [D(2026, 8, 1), D(2026, 9, 1), D(2026, 10, 1)],
        )

    def test_generation_copies_the_bill_amount(self):
        bill = self.make_bill(D(2026, 8, 1), amount="1234.56")

        self.service.generate_occurrences(bill, today=D(2026, 7, 28))

        for occurrence in bill.occurrences.all():
            self.assertEqual(str(occurrence.amount), "1234.56")

    def test_generation_is_idempotent(self):
        bill = self.make_bill(D(2026, 8, 1))
        today = D(2026, 7, 28)

        self.service.generate_occurrences(bill, today=today)
        before = bill.occurrences.count()

        second = self.service.generate_occurrences(bill, today=today)

        self.assertEqual(second, [])
        self.assertEqual(bill.occurrences.count(), before)

    def test_rerunning_later_extends_the_horizon(self):
        bill = self.make_bill(D(2026, 8, 1))

        self.service.generate_occurrences(bill, today=D(2026, 7, 28))
        self.service.generate_occurrences(bill, today=D(2026, 9, 2))

        self.assertEqual(
            list(
                bill.occurrences.order_by("due_date").values_list(
                    "due_date", flat=True
                )
            ),
            [
                D(2026, 8, 1),
                D(2026, 9, 1),
                D(2026, 10, 1),
                D(2026, 11, 1),
            ],
        )

    def test_generation_does_not_disturb_a_paid_occurrence(self):
        bill = self.make_bill(D(2026, 8, 1))
        self.service.generate_occurrences(bill, today=D(2026, 7, 28))

        paid = bill.occurrences.order_by("due_date").first()
        paid.status = BillOccurrenceStatus.PAID
        paid.save(update_fields=["status"])

        self.service.generate_occurrences(bill, today=D(2026, 7, 28))

        paid.refresh_from_db()
        self.assertEqual(paid.status, BillOccurrenceStatus.PAID)

    def test_one_time_bill_never_gains_a_second_occurrence(self):
        bill = self.make_bill(D(2026, 8, 1), frequency=BillFrequency.ONE_TIME)

        self.service.generate_occurrences(bill, today=D(2026, 7, 28))
        self.service.generate_occurrences(bill, today=D(2027, 7, 28))

        self.assertEqual(bill.occurrences.count(), 1)


class ComputedStatusTests(OccurrenceTestCase):

    def annotate_one(self, occurrence, today):
        return annotate_status(
            BillOccurrence.objects.filter(pk=occurrence.pk), today
        ).first().computed_status

    def test_status_transitions_with_the_calendar_alone(self):
        """The same stored row reads UPCOMING, DUE then OVERDUE."""
        bill = self.make_bill(D(2026, 8, 1))
        self.service.generate_occurrences(bill, today=D(2026, 7, 28))

        occurrence = bill.occurrences.order_by("due_date").first()
        self.assertEqual(occurrence.status, BillOccurrenceStatus.UPCOMING)

        cases = [
            (D(2026, 7, 28), BillOccurrenceStatus.UPCOMING),
            (D(2026, 8, 1), BillOccurrenceStatus.DUE),
            (D(2026, 8, 2), BillOccurrenceStatus.OVERDUE),
        ]

        for today, expected in cases:
            with self.subTest(today=today):
                self.assertEqual(
                    self.annotate_one(occurrence, today), expected
                )

        occurrence.refresh_from_db()
        self.assertEqual(
            occurrence.status,
            BillOccurrenceStatus.UPCOMING,
            msg="stored status must never be rewritten by a read",
        )

    def test_paid_beats_the_calendar(self):
        bill = self.make_bill(D(2026, 8, 1))
        self.service.generate_occurrences(bill, today=D(2026, 7, 28))

        occurrence = bill.occurrences.order_by("due_date").first()
        occurrence.status = BillOccurrenceStatus.PAID
        occurrence.save(update_fields=["status"])

        self.assertEqual(
            self.annotate_one(occurrence, D(2027, 1, 1)),
            BillOccurrenceStatus.PAID,
        )

    def test_scheduled_beats_the_calendar(self):
        bill = self.make_bill(D(2026, 8, 1))
        self.service.generate_occurrences(bill, today=D(2026, 7, 28))

        occurrence = bill.occurrences.order_by("due_date").first()
        occurrence.status = BillOccurrenceStatus.SCHEDULED
        occurrence.save(update_fields=["status"])

        self.assertEqual(
            self.annotate_one(occurrence, D(2027, 1, 1)),
            BillOccurrenceStatus.SCHEDULED,
        )


class SummaryTests(OccurrenceTestCase):

    def test_counts_split_across_overdue_due_and_upcoming(self):
        bill = self.make_bill(D(2026, 1, 15), amount="100.00")
        today = D(2026, 7, 15)

        for due_date in (D(2026, 7, 10), D(2026, 7, 15), D(2026, 7, 20)):
            BillOccurrence.objects.create(
                bill=bill, due_date=due_date, amount="100.00"
            )

        summary = self.selector.get_summary(self.user, today=today)

        self.assertEqual(summary["overdue_count"], 1)
        self.assertEqual(summary["due_count"], 1)
        self.assertEqual(summary["upcoming_count"], 1)

    def test_settled_occurrences_leave_the_counts_and_the_total(self):
        bill = self.make_bill(D(2026, 1, 15), amount="100.00")
        today = D(2026, 7, 15)

        BillOccurrence.objects.create(
            bill=bill, due_date=D(2026, 7, 10), amount="100.00",
            status=BillOccurrenceStatus.PAID,
        )
        BillOccurrence.objects.create(
            bill=bill, due_date=D(2026, 7, 20), amount="250.00",
        )

        summary = self.selector.get_summary(self.user, today=today)

        self.assertEqual(summary["overdue_count"], 0)
        self.assertEqual(summary["upcoming_count"], 1)
        self.assertEqual(
            Decimal(summary["total_due_this_month"]), Decimal("250.00")
        )

    def test_next_due_skips_settled_occurrences(self):
        bill = self.make_bill(D(2026, 1, 15), amount="100.00")
        today = D(2026, 7, 15)

        BillOccurrence.objects.create(
            bill=bill, due_date=D(2026, 7, 20), amount="100.00",
            status=BillOccurrenceStatus.SCHEDULED,
        )
        expected = BillOccurrence.objects.create(
            bill=bill, due_date=D(2026, 7, 25), amount="100.00",
        )

        self.assertEqual(
            self.selector.get_next_due(self.user, today=today).pk,
            expected.pk,
        )

    def test_next_due_is_none_when_nothing_is_outstanding(self):
        self.make_bill(D(2026, 1, 15))

        self.assertIsNone(
            self.selector.get_next_due(self.user, today=D(2026, 7, 15))
        )
