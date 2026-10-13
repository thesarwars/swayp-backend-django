"""Edit / delete schedule semantics (E4-S5).

Every case here is written against a fixed calendar anchored at 2026-08-01,
which reads clearly but carried a hidden assumption: that the anchor is still
in the future. On 2026-08-01 that stopped being true and four cases began
failing, with nothing in any diff to explain why — the code had not changed,
the calendar had.

"Today" is therefore pinned rather than read from the clock. The assumption
the file always relied on is now written down and cannot expire again.
"""

import datetime as dt
from unittest import mock

from django.test import TestCase

from apps.bill_categories.models import BillCategory
from apps.bills.models.bill import Bill
from apps.bills.models.bill_occurrence import BillOccurrence
from apps.bills.services.bill_service import BillService
from apps.common.enums import (
    BillFrequency,
    BillOccurrenceStatus,
    BillType,
)
from apps.users.models import User
from apps.vendors.models import Vendor

D = dt.date


#: A month before the fixture's anchor date, so every bill in this file is
#: genuinely upcoming — which is what each case was written to assume.
TODAY = D(2026, 7, 1)


class BillEditDeleteTestCase(TestCase):

    def setUp(self):
        # Patched at each module that reads it rather than at the definition:
        # they import the function by name, so patching apps.common.dates
        # alone would leave every one of these call sites on the real clock.
        #
        # The occurrence engine reads timezone.localdate() instead, which is a
        # separate clock and has to be pinned too — pinning only one of the
        # two produces a schedule built against today and read against a
        # different day, which is worse than pinning neither.
        for target in (
            "apps.bills.selectors.bill_occurrence_selector.today_eastern",
            "apps.bills.selectors.occurrence_status.today_eastern",
            "apps.bills.serializers.bill_detail_serializer.today_eastern",
            "apps.bills.services.bill_occurrence_service.timezone.localdate",
        ):
            patcher = mock.patch(target, return_value=TODAY)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.service = BillService()

        self.user = User.objects.create_user(
            email="editdelete@example.com",
            password="Sw@yp-Test-1",
        )
        self.category = BillCategory.objects.get_or_create(
            name="Rent",
            defaults={"icon": "https://e.com/i.png", "color": "#111"},
        )[0]
        self.vendor = Vendor.objects.create(
            user=self.user, name="WeWork", category=self.category,
        )

    def make_bill(self, **overrides):
        payload = {
            "vendor": self.vendor.id,
            "category": self.category.id,
            "bill_type": BillType.FIXED,
            "amount": "3200.00",
            "frequency": BillFrequency.MONTHLY,
            "anchor_date": D(2026, 8, 1),
            "autopay_mode": "REMIND",
            "source": "MANUAL",
            "notes": "",
        }
        payload.update(overrides)

        return self.service.create_bill(
            user=self.user, validated_data=payload
        )

    def due_dates(self, bill):
        return list(
            bill.occurrences.order_by("due_date").values_list(
                "due_date", flat=True
            )
        )

    def settle(self, bill, due_date, status=BillOccurrenceStatus.PAID):
        occurrence = bill.occurrences.get(due_date=due_date)
        occurrence.status = status
        occurrence.save(update_fields=["status"])
        return occurrence


class ScheduleRebuildTests(BillEditDeleteTestCase):

    def test_changing_frequency_rebuilds_the_schedule(self):
        bill = self.make_bill()
        self.assertEqual(
            self.due_dates(bill),
            [D(2026, 8, 1), D(2026, 9, 1), D(2026, 10, 1)],
        )

        self.service.update_bill(
            bill_id=bill.id,
            user=self.user,
            validated_data={"frequency": BillFrequency.WEEKLY},
        )

        # Weekly from the same anchor — the old monthly dates are gone.
        self.assertEqual(
            self.due_dates(bill),
            [D(2026, 8, 1), D(2026, 8, 8), D(2026, 8, 15)],
        )

    def test_changing_anchor_date_rebuilds_the_schedule(self):
        bill = self.make_bill()

        self.service.update_bill(
            bill_id=bill.id,
            user=self.user,
            validated_data={"anchor_date": D(2026, 8, 20)},
        )

        self.assertEqual(
            self.due_dates(bill),
            [D(2026, 8, 20), D(2026, 9, 20), D(2026, 10, 20)],
        )

    def test_rebuild_keeps_settled_occurrences(self):
        bill = self.make_bill()
        self.settle(bill, D(2026, 9, 1))

        self.service.update_bill(
            bill_id=bill.id,
            user=self.user,
            validated_data={"frequency": BillFrequency.WEEKLY},
        )

        self.assertIn(D(2026, 9, 1), self.due_dates(bill))
        self.assertEqual(
            bill.occurrences.get(due_date=D(2026, 9, 1)).status,
            BillOccurrenceStatus.PAID,
        )

    def test_scheduled_occurrences_also_survive_a_rebuild(self):
        bill = self.make_bill()
        self.settle(
            bill, D(2026, 9, 1), status=BillOccurrenceStatus.SCHEDULED
        )

        self.service.update_bill(
            bill_id=bill.id,
            user=self.user,
            validated_data={"anchor_date": D(2026, 8, 20)},
        )

        self.assertIn(D(2026, 9, 1), self.due_dates(bill))

    def test_editing_an_unrelated_field_leaves_the_schedule_alone(self):
        bill = self.make_bill()
        before = self.due_dates(bill)

        self.service.update_bill(
            bill_id=bill.id,
            user=self.user,
            validated_data={"notes": "changed"},
        )

        self.assertEqual(self.due_dates(bill), before)

    def test_setting_the_same_frequency_is_not_a_rebuild(self):
        bill = self.make_bill()
        ids_before = set(
            bill.occurrences.values_list("id", flat=True)
        )

        self.service.update_bill(
            bill_id=bill.id,
            user=self.user,
            validated_data={"frequency": BillFrequency.MONTHLY},
        )

        self.assertEqual(
            set(bill.occurrences.values_list("id", flat=True)),
            ids_before,
        )


class RepricingTests(BillEditDeleteTestCase):

    def test_new_amount_reaches_unsettled_occurrences(self):
        bill = self.make_bill()

        self.service.update_bill(
            bill_id=bill.id,
            user=self.user,
            validated_data={"amount": "4000.00"},
        )

        for occurrence in bill.occurrences.all():
            self.assertEqual(str(occurrence.amount), "4000.00")

    def test_settled_occurrences_keep_the_amount_that_was_paid(self):
        bill = self.make_bill()
        self.settle(bill, D(2026, 8, 1))

        self.service.update_bill(
            bill_id=bill.id,
            user=self.user,
            validated_data={"amount": "4000.00"},
        )

        self.assertEqual(
            str(bill.occurrences.get(due_date=D(2026, 8, 1)).amount),
            "3200.00",
        )

    def test_variable_bills_keep_their_per_occurrence_overrides(self):
        bill = self.make_bill(bill_type=BillType.VARIABLE)

        overridden = bill.occurrences.order_by("due_date").last()
        overridden.amount = "999.00"
        overridden.save(update_fields=["amount"])

        self.service.update_bill(
            bill_id=bill.id,
            user=self.user,
            validated_data={"amount": "4000.00"},
        )

        overridden.refresh_from_db()
        self.assertEqual(str(overridden.amount), "999.00")


class SoftDeleteTests(BillEditDeleteTestCase):

    def test_delete_preserves_paid_history(self):
        bill = self.make_bill()
        paid = self.settle(bill, D(2026, 8, 1))

        self.service.delete_bill(bill_id=bill.id, user=self.user)

        self.assertTrue(
            BillOccurrence.objects.filter(pk=paid.pk).exists(),
            msg="paid occurrences must survive a bill delete",
        )
        self.assertTrue(Bill.objects.filter(pk=bill.pk).exists())

    def test_delete_removes_future_unpaid_occurrences(self):
        bill = self.make_bill()
        self.settle(bill, D(2026, 8, 1))

        self.service.delete_bill(bill_id=bill.id, user=self.user)

        self.assertEqual(self.due_dates(bill), [D(2026, 8, 1)])

    def test_deleted_bill_disappears_from_listings(self):
        bill = self.make_bill()

        self.service.delete_bill(bill_id=bill.id, user=self.user)

        self.assertEqual(
            list(self.service.get_user_bills(self.user)), []
        )

    def test_deleted_bill_is_no_longer_retrievable(self):
        bill = self.make_bill()
        self.service.delete_bill(bill_id=bill.id, user=self.user)

        with self.assertRaises(Exception):
            self.service.get_bill(bill_id=bill.id, user=self.user)

    def test_deleted_bill_occurrences_leave_the_summary(self):
        bill = self.make_bill()

        before = self.service.occurrence_service.get_summary(self.user)
        self.assertEqual(before["upcoming_count"], 3)

        self.service.delete_bill(bill_id=bill.id, user=self.user)

        after = self.service.occurrence_service.get_summary(self.user)
        self.assertEqual(after["upcoming_count"], 0)

    def test_beat_job_skips_deleted_bills(self):
        from apps.bills.tasks import generate_occurrences

        bill = self.make_bill()
        self.service.delete_bill(bill_id=bill.id, user=self.user)

        generate_occurrences()

        self.assertEqual(bill.occurrences.count(), 0)
