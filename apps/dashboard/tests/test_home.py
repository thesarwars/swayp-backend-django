"""E8-S1 — GET dashboard/home/, the one round-trip behind the landing screen.

Two things are being proved here. First that the aggregate costs a fixed five
queries no matter how much data the account holds, because the screen is the
first thing every user sees. Second that its numbers are the *same* numbers
bills/summary/ and vendors/summary/ publish — not numbers that happen to agree
today. Every reconciliation test therefore fetches both endpoints over HTTP for
one user and compares, rather than asserting two hardcoded constants.
"""

import calendar
import datetime as dt
import time
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.bills.models.bill_occurrence import BillOccurrence
from apps.common.dates import today_eastern
from apps.common.enums import (
    BillOccurrenceStatus,
    VendorPaymentMethodType,
    VendorStatus,
)
from apps.dashboard.services.home_service import (
    PAY_PANEL_ITEM_LIMIT,
    RECENT_BILLS_LIMIT,
    VENDORS_PREVIEW_LIMIT,
)
from apps.vendors.factories import (
    BillCategoryFactory,
    UserFactory,
    VendorFactory,
    VendorPaymentMethodFactory,
)

HOME_URL = "/api/v1/dashboard/home"
BILLS_URL = "/api/v1/bills"
BILLS_SUMMARY_URL = "/api/v1/bills/summary"
OCCURRENCES_URL = "/api/v1/bills/occurrences"
VENDORS_URL = "/api/v1/vendors"
VENDORS_SUMMARY_URL = "/api/v1/vendors/summary"

#: The endpoint issues one aggregate, one bill count, one recent-bills read,
#: one vendor-preview read and one pay-panel read — plus one membership
#: lookup to resolve which account the caller acts on (E10). Exact by
#: design: this is the N+1 guard, so a seventh query has to be a deliberate
#: edit to this number.
#:
#: The membership lookup is a single indexed read, memoised per request, so
#: it is a constant and not a per-row cost — which is what
#: test_home_query_count_is_independent_of_row_count actually guards.
EXPECTED_QUERIES = 6

#: A regression tripwire for AC3, not a production p95 — the suite runs on
#: in-memory SQLite. The budget is the epic's 500 ms so the number stays
#: recognisable; the real figure here is two orders of magnitude smaller.
P95_BUDGET_SECONDS = 0.5


class HomeTestCase(TestCase):
    """Fixture helpers. Both bill factories hardcode 2026-08-01, so every due
    date here is expressed relative to today_eastern() instead."""

    def setUp(self):
        self.today = today_eastern()
        self.user = UserFactory()
        self.category = BillCategoryFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    # --- date helpers -----------------------------------------------------

    def _days(self, offset):
        return self.today + dt.timedelta(days=offset)

    def _in_month(self, day):
        """A date inside today's calendar month, whatever today happens to be.

        The month-scoped figures (due_this_month, paid, monthly_amount) cannot
        use today +/- N: on the 1st or the 31st that silently lands in a
        neighbouring month and the assertion becomes calendar-dependent.
        """
        last = calendar.monthrange(self.today.year, self.today.month)[1]
        return dt.date(self.today.year, self.today.month, min(day, last))

    def _month_days_avoiding(self, count, *taken):
        """``count`` dates inside today's month that collide with nothing.

        bill_occurrences carries UniqueConstraint(bill, due_date), so a bill
        that needs both month-anchored dates (for due_this_month / paid) and
        today-relative ones (for the tab counts) cannot spell the month-anchored
        ones as fixed day numbers: day 1 *is* today on the 1st, and today-3 on
        the 4th. Hardcoding them makes the fixture raise IntegrityError on 48
        days of the year and pass on the rest, which is a green suite that goes
        red on a date. Choosing the month-anchored days around the
        today-relative ones removes the calendar from the fixture entirely.
        """
        this_month = (self.today.year, self.today.month)
        taken_days = {
            date.day
            for date in taken
            if (date.year, date.month) == this_month
        }
        last = calendar.monthrange(*this_month)[1]
        free = [day for day in range(1, last + 1) if day not in taken_days]

        self.assertGreaterEqual(len(free), count)

        return [dt.date(*this_month, day) for day in free[:count]]

    def _last_month(self, day=15):
        end_of_previous = self.today.replace(day=1) - dt.timedelta(days=1)
        return end_of_previous.replace(day=min(day, end_of_previous.day))

    def _next_month(self, day=15):
        first_of_next = (
            self.today.replace(day=1)
            + dt.timedelta(days=32)
        ).replace(day=1)
        return first_of_next.replace(day=day)

    # --- object helpers ---------------------------------------------------

    def _vendor(self, user=None, **kwargs):
        return VendorFactory(
            user=user or self.user, category=self.category, **kwargs
        )

    def _bill(self, vendor=None, user=None, amount="3200.00", **kwargs):
        owner = user or self.user

        return BillFactory(
            user=owner,
            vendor=vendor if vendor is not None else self._vendor(owner),
            category=self.category,
            amount=Decimal(amount),
            anchor_date=self.today,
            **kwargs,
        )

    def _occurrence(
        self,
        due_date,
        bill=None,
        amount="100.00",
        status=BillOccurrenceStatus.UPCOMING,
    ):
        return BillOccurrenceFactory(
            bill=bill if bill is not None else self._bill(),
            due_date=due_date,
            amount=Decimal(amount),
            status=status,
        )

    # --- fixtures shared with the calendar guard below --------------------

    def _seed_mixed_month(self):
        """Paid, scheduled, overdue, due-today, future, and two other months."""
        bill = self._bill()

        overdue, due, future = self._days(-3), self._days(0), self._days(6)
        paid_day, scheduled_day = self._month_days_avoiding(
            2, overdue, due, future
        )

        self._occurrence(
            paid_day,
            bill=bill,
            amount="400.00",
            status=BillOccurrenceStatus.PAID,
        )
        self._occurrence(
            scheduled_day,
            bill=bill,
            amount="150.00",
            status=BillOccurrenceStatus.SCHEDULED,
        )
        self._occurrence(overdue, bill=bill, amount="220.00")
        self._occurrence(due, bill=bill, amount="330.00")
        self._occurrence(future, bill=bill, amount="440.00")
        self._occurrence(self._next_month(), bill=bill, amount="900.00")
        self._occurrence(self._last_month(), bill=bill, amount="800.00")

        return bill

    def _seed_deletable_bill(self):
        """One bill carrying an overdue, a due, an upcoming and a paid row."""
        bill = self._bill(amount="4000.00")

        overdue = self._occurrence(self._days(-2), bill=bill, amount="60.00")
        due = self._occurrence(self._days(0), bill=bill, amount="70.00")
        upcoming = self._occurrence(self._days(2), bill=bill, amount="80.00")
        (paid_day,) = self._month_days_avoiding(
            1, overdue.due_date, due.due_date, upcoming.due_date
        )
        paid = self._occurrence(
            paid_day,
            bill=bill,
            amount="90.00",
            status=BillOccurrenceStatus.PAID,
        )

        return bill, (overdue, due, upcoming, paid)

    # --- request helpers --------------------------------------------------

    def _home(self, **params):
        response = self.client.get(HOME_URL, params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data["data"]

    def _bills_summary(self):
        response = self.client.get(BILLS_SUMMARY_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data["data"]


class HomeQueryCountTests(HomeTestCase):

    def _seed_small(self):
        vendor_a, vendor_b = self._vendor(), self._vendor()
        bills = [
            self._bill(vendor=vendor_a),
            self._bill(vendor=vendor_b),
            self._bill(vendor=vendor_b),
        ]

        for index, offset in enumerate((-9, -4, -1, 0, 1, 3, 8, 15)):
            self._occurrence(
                self._days(offset),
                bill=bills[index % len(bills)],
                amount="250.00",
            )

    def _seed_large(self, occurrences=1000, vendors=12, bills=40):
        vendor_rows = [self._vendor() for _ in range(vendors)]
        bill_rows = [
            self._bill(vendor=vendor_rows[index % vendors])
            for index in range(bills)
        ]

        per_bill = occurrences // bills
        statuses = (
            BillOccurrenceStatus.UPCOMING,
            BillOccurrenceStatus.PAID,
            BillOccurrenceStatus.SCHEDULED,
        )

        BillOccurrence.objects.bulk_create(
            BillOccurrence(
                bill=bill_rows[index // per_bill],
                # Spread across overdue / due / upcoming, unique per bill.
                due_date=self._days(index % per_bill - per_bill // 2),
                amount=Decimal("175.25"),
                status=statuses[index % len(statuses)],
            )
            for index in range(occurrences)
        )

    def test_home_costs_a_fixed_number_of_queries(self):
        self._seed_small()

        with self.assertNumQueries(EXPECTED_QUERIES):
            self.client.get(HOME_URL)

    def test_home_query_count_is_independent_of_row_count(self):
        self._seed_large()

        self.assertEqual(
            BillOccurrence.objects.filter(bill__user=self.user).count(), 1000
        )

        with self.assertNumQueries(EXPECTED_QUERIES):
            self.client.get(HOME_URL)

    def test_home_p95_stays_within_budget_at_1k_occurrences(self):
        """AC3, as a tripwire rather than a production measurement."""
        self._seed_large()

        samples = []
        for _ in range(20):
            started = time.perf_counter()
            self.client.get(HOME_URL)
            samples.append(time.perf_counter() - started)

        samples.sort()
        p95 = samples[int(len(samples) * 0.95) - 1]

        self.assertLess(p95, P95_BUDGET_SECONDS, f"p95 {p95:.3f}s")


class HomeReconciliationTests(HomeTestCase):

    def test_due_this_month_matches_bills_summary(self):
        self._seed_mixed_month()

        home = self._home()
        summary = self._bills_summary()

        self.assertEqual(
            home["stats"]["due_this_month"], summary["total_due_this_month"]
        )
        # Not the trivially-equal "0.00" case.
        self.assertNotEqual(home["stats"]["due_this_month"], "0.00")

    def test_tab_counts_match_bills_summary(self):
        self._seed_mixed_month()

        home = self._home()
        summary = self._bills_summary()

        self.assertEqual(
            home["pay_panel"]["tabs"],
            {
                "overdue": summary["overdue_count"],
                "due": summary["due_count"],
                "upcoming": summary["upcoming_count"],
            },
        )
        self.assertGreater(summary["overdue_count"], 0)

    def test_total_bills_and_paid_match_bills_summary(self):
        self._seed_mixed_month()

        home = self._home()
        summary = self._bills_summary()

        self.assertEqual(home["stats"]["total_bills"], summary["total_bills"])
        self.assertEqual(home["stats"]["paid"], summary["paid_count"])
        self.assertEqual(summary["paid_count"], 1)

    def test_total_bills_counts_bills_not_occurrences(self):
        bills = [self._bill() for _ in range(3)]

        for bill in bills:
            for offset in range(4):
                self._occurrence(self._days(offset), bill=bill)

        home = self._home()
        listing = self.client.get(BILLS_URL)

        self.assertEqual(
            BillOccurrence.objects.filter(bill__user=self.user).count(), 12
        )
        self.assertEqual(home["stats"]["total_bills"], 3)
        self.assertEqual(len(listing.data["data"]), 3)

    def test_paid_counts_only_this_months_settled_occurrences(self):
        bill = self._bill()

        self._occurrence(
            self._in_month(1),
            bill=bill,
            amount="100.00",
            status=BillOccurrenceStatus.PAID,
        )
        self._occurrence(
            self._in_month(2),
            bill=bill,
            amount="100.00",
            status=BillOccurrenceStatus.PAID,
        )
        self._occurrence(
            self._last_month(),
            bill=bill,
            amount="100.00",
            status=BillOccurrenceStatus.PAID,
        )
        self._occurrence(self._in_month(3), bill=bill, amount="100.00")

        self.assertEqual(self._home()["stats"]["paid"], 2)

    def test_scheduled_occurrence_is_in_neither_due_this_month_nor_paid_nor_any_tab(
        self,
    ):
        """A payment in flight has no home on this card. Recorded, not fixed.

        SCHEDULED is terminal for the calendar (status_expression returns it
        verbatim) and is excluded from the open-occurrence total, so the row is
        in none of the five numbers. That matches bills/summary/, which is the
        reconciliation target — the fix is a sixth conditional count, and it
        belongs to whoever adds the "In flight" chip.
        """
        self._occurrence(
            self._days(0),
            amount="500.00",
            status=BillOccurrenceStatus.SCHEDULED,
        )

        home = self._home()

        self.assertEqual(home["stats"]["due_this_month"], "0.00")
        self.assertEqual(home["stats"]["paid"], 0)
        self.assertEqual(
            home["pay_panel"]["tabs"],
            {"overdue": 0, "due": 0, "upcoming": 0},
        )

    def test_vendors_preview_rowset_is_the_one_vendors_summary_counts(self):
        """Every preview row is a row vendors/summary/ counted.

        Deliberately *not* ``len(preview) == summary.total``: the preview is
        capped at VENDORS_PREVIEW_LIMIT, so that equality holds only while the
        fixture stays smaller than the cap. It is an artefact of the fixture
        size, not the invariant — and it would go false, with no bug, the day
        anyone raises the limit or adds a fourth vendor. The invariant is
        containment, so the fixture is seeded past the cap on purpose.
        """
        active = [
            self._vendor(name=f"Active {index}")
            for index in range(VENDORS_PREVIEW_LIMIT + 3)
        ]
        # Named to sort first: every vendor here bills 0.00 this month, so the
        # tie-break is the name, and a deleted vendor called "Gone" would fall
        # off the end of the top 3 for the wrong reason.
        self._vendor(name="AAA Deleted", status=VendorStatus.DELETED)

        home = self._home()
        vendors_summary = self.client.get(VENDORS_SUMMARY_URL).data
        listing = self.client.get(VENDORS_URL).data

        preview_ids = [row["id"] for row in home["vendors_preview"]]
        listed_ids = {row["id"] for row in listing["items"]}

        # The cap is genuinely biting, so containment is the only thing left
        # for the assertion below to be testing.
        self.assertEqual(len(preview_ids), VENDORS_PREVIEW_LIMIT)
        self.assertLess(len(preview_ids), vendors_summary["total"])

        # vendors/summary/ is literally VendorSelector.list(user).count(), and
        # GET vendors/ serialises that same rowset — so this is the subset
        # relation the AC asks for, on the rows rather than on a length.
        self.assertEqual(vendors_summary["total"], len(active))
        self.assertEqual(len(listed_ids), vendors_summary["total"])
        self.assertLessEqual(set(preview_ids), listed_ids)

        self.assertNotIn(
            "AAA Deleted", [row["name"] for row in home["vendors_preview"]]
        )


class PayPanelTests(HomeTestCase):

    def test_pay_panel_preloads_overdue_by_default(self):
        bill = self._bill()
        self._occurrence(self._days(-2), bill=bill)
        self._occurrence(self._days(-1), bill=bill)
        self._occurrence(self._days(0), bill=bill)
        self._occurrence(self._days(4), bill=bill)

        panel = self._home()["pay_panel"]

        self.assertEqual(panel["active_tab"], "overdue")
        self.assertEqual(len(panel["items"]), 2)
        self.assertEqual(
            {row["status"] for row in panel["items"]}, {"OVERDUE"}
        )

    def test_pay_panel_falls_back_to_due_then_upcoming_when_overdue_is_empty(
        self,
    ):
        bill = self._bill()
        self._occurrence(self._days(0), bill=bill)

        with self.assertNumQueries(EXPECTED_QUERIES):
            response = self.client.get(HOME_URL)

        panel = response.data["data"]["pay_panel"]
        self.assertEqual(panel["active_tab"], "due")
        self.assertEqual({row["status"] for row in panel["items"]}, {"DUE"})

        # Nothing overdue and nothing due: the panel must still land on rows.
        BillOccurrence.objects.filter(bill=bill).delete()
        self._occurrence(self._days(9), bill=bill)

        with self.assertNumQueries(EXPECTED_QUERIES):
            response = self.client.get(HOME_URL)

        panel = response.data["data"]["pay_panel"]
        self.assertEqual(panel["active_tab"], "upcoming")
        self.assertEqual(len(panel["items"]), 1)
        self.assertEqual(panel["items"][0]["status"], "UPCOMING")

    def test_pay_panel_items_are_identical_to_the_occurrences_endpoint(self):
        bill = self._bill()
        for offset in range(1, 8):
            self._occurrence(
                self._days(-offset), bill=bill, amount=f"{100 + offset}.00"
            )

        home = self._home()
        occurrences = self.client.get(OCCURRENCES_URL, {"status": "OVERDUE"})

        self.assertEqual(
            home["pay_panel"]["items"],
            list(occurrences.data["data"][:PAY_PANEL_ITEM_LIMIT]),
        )

    def test_tab_query_param_overrides_the_default(self):
        bill = self._bill()
        self._occurrence(self._days(-1), bill=bill)
        self._occurrence(self._days(5), bill=bill)

        with self.assertNumQueries(EXPECTED_QUERIES):
            response = self.client.get(HOME_URL, {"tab": "upcoming"})

        panel = response.data["data"]["pay_panel"]

        self.assertEqual(panel["active_tab"], "upcoming")
        self.assertEqual(
            {row["status"] for row in panel["items"]}, {"UPCOMING"}
        )
        # The counts do not follow the selected tab.
        self.assertEqual(panel["tabs"]["overdue"], 1)

    def test_unknown_tab_is_rejected_with_400(self):
        response = self.client.get(HOME_URL, {"tab": "paid"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pay_panel_items_are_capped(self):
        bill = self._bill()
        for offset in range(1, 31):
            self._occurrence(self._days(-offset), bill=bill)

        panel = self._home()["pay_panel"]

        self.assertEqual(len(panel["items"]), PAY_PANEL_ITEM_LIMIT)
        self.assertEqual(panel["tabs"]["overdue"], 30)


class RecentBillsTests(HomeTestCase):

    def test_recent_bills_are_the_most_recently_due_including_settled(self):
        bill = self._bill()
        self._occurrence(self._days(-1), bill=bill, amount="10.00")
        self._occurrence(self._days(-5), bill=bill, amount="20.00")
        self._occurrence(
            self._days(-20),
            bill=bill,
            amount="30.00",
            status=BillOccurrenceStatus.PAID,
        )
        self._occurrence(self._days(3), bill=bill, amount="40.00")

        rows = self._home()["recent_bills"]

        self.assertEqual(
            [row["due_date"] for row in rows],
            [
                self._days(-1).isoformat(),
                self._days(-5).isoformat(),
                self._days(-20).isoformat(),
            ],
        )
        self.assertEqual(rows[-1]["status"], "PAID")

    def test_recent_bills_carry_the_computed_status_not_the_stored_default(
        self,
    ):
        occurrence = self._occurrence(
            self._days(-3), status=BillOccurrenceStatus.UPCOMING
        )

        rows = self._home()["recent_bills"]

        self.assertEqual(occurrence.status, BillOccurrenceStatus.UPCOMING)
        self.assertEqual(rows[0]["status"], "OVERDUE")

    def test_recent_bills_are_capped_at_five(self):
        bill = self._bill()
        for offset in range(1, 21):
            self._occurrence(self._days(-offset), bill=bill)

        self.assertEqual(
            len(self._home()["recent_bills"]), RECENT_BILLS_LIMIT
        )


class VendorsPreviewTests(HomeTestCase):

    def test_vendors_preview_is_top_three_by_this_months_amount(self):
        small = self._vendor(name="Small")
        biggest = self._vendor(name="Biggest")
        middling = self._vendor(name="Middling")
        self._vendor(name="Nothing")

        self._occurrence(
            self._in_month(1), bill=self._bill(vendor=small), amount="150.00"
        )

        big_bill = self._bill(vendor=biggest)
        self._occurrence(self._in_month(1), bill=big_bill, amount="2000.00")
        self._occurrence(self._in_month(2), bill=big_bill, amount="1200.00")

        self._occurrence(
            self._in_month(3),
            bill=self._bill(vendor=middling),
            amount="900.00",
        )

        rows = self._home()["vendors_preview"]

        self.assertEqual(len(rows), VENDORS_PREVIEW_LIMIT)
        self.assertEqual(
            [(row["name"], row["monthly_amount"]) for row in rows],
            [
                ("Biggest", "3200.00"),
                ("Middling", "900.00"),
                ("Small", "150.00"),
            ],
        )

    def test_vendors_preview_monthly_amount_excludes_other_months_and_deleted_bills(
        self,
    ):
        vendor = self._vendor(name="Quiet")

        self._occurrence(
            self._next_month(),
            bill=self._bill(vendor=vendor),
            amount="1000.00",
        )

        deleted_bill = self._bill(vendor=vendor)
        self._occurrence(
            self._in_month(1), bill=deleted_bill, amount="500.00"
        )
        deleted_bill.deleted_at = timezone.now()
        deleted_bill.save(update_fields=["deleted_at"])

        rows = self._home()["vendors_preview"]

        self.assertEqual(rows[0]["name"], "Quiet")
        self.assertEqual(rows[0]["monthly_amount"], "0.00")

    def test_vendors_preview_rail_is_the_primary_payment_method(self):
        by_check = self._vendor(name="Checky")
        VendorPaymentMethodFactory(vendor=by_check, check=True)
        VendorPaymentMethodFactory(vendor=by_check, is_primary=False)

        self._vendor(name="Railless")

        rows = {row["name"]: row for row in self._home()["vendors_preview"]}

        self.assertEqual(
            rows["Checky"]["rail"], VendorPaymentMethodType.CHECK
        )
        self.assertIsNone(rows["Railless"]["rail"])


class HomeIsolationTests(HomeTestCase):

    def test_soft_deleted_bill_disappears_from_every_section(self):
        keeper = self._bill()
        self._occurrence(self._days(-1), bill=keeper, amount="11.00")

        doomed, (overdue, due, upcoming, _paid) = self._seed_deletable_bill()

        before = self._home()

        doomed.deleted_at = timezone.now()
        doomed.save(update_fields=["deleted_at"])

        after = self._home()

        # Only the open occurrences that fall in this calendar month were ever
        # in due_this_month, so that is the drop to expect.
        expected_drop = sum(
            occurrence.amount
            for occurrence in (overdue, due, upcoming)
            if (occurrence.due_date.year, occurrence.due_date.month)
            == (self.today.year, self.today.month)
        )

        self.assertEqual(
            after["stats"]["total_bills"], before["stats"]["total_bills"] - 1
        )
        self.assertEqual(
            Decimal(before["stats"]["due_this_month"])
            - Decimal(after["stats"]["due_this_month"]),
            expected_drop,
        )
        self.assertEqual(before["stats"]["paid"] - after["stats"]["paid"], 1)

        for tab in ("overdue", "due", "upcoming"):
            self.assertEqual(
                after["pay_panel"]["tabs"][tab],
                before["pay_panel"]["tabs"][tab] - 1,
                tab,
            )

        surviving = {str(occurrence.id) for occurrence in doomed.occurrences.all()}
        shown = {row["id"] for row in after["recent_bills"]} | {
            row["id"] for row in after["pay_panel"]["items"]
        }

        self.assertEqual(surviving & shown, set())

    def test_another_users_data_never_appears(self):
        stranger = UserFactory()
        stranger_vendor = self._vendor(user=stranger, name="Not Yours")
        stranger_bill = self._bill(
            user=stranger, vendor=stranger_vendor, amount="5000.00"
        )

        for offset in (-2, 0, 3):
            self._occurrence(
                self._days(offset), bill=stranger_bill, amount="999.00"
            )

        # A bill the stranger owns pointed at *my* vendor. Nothing in the
        # schema or the model forces bill.user == bill.vendor.user, and the
        # preview's monthly Sum walks vendor -> bills -> occurrences, so that
        # join has to be scoped by the bill's owner and not only by the
        # vendor's. Without it my card displays his money.
        mine = self._vendor(name="Mine")
        crossed = self._bill(user=stranger, vendor=mine, amount="777.00")
        self._occurrence(self._days(0), bill=crossed, amount="777.00")

        home = self._home()

        self.assertEqual(home["stats"]["due_this_month"], "0.00")
        self.assertEqual(home["stats"]["total_bills"], 0)
        self.assertEqual(home["stats"]["paid"], 0)
        self.assertEqual(
            home["pay_panel"]["tabs"],
            {"overdue": 0, "due": 0, "upcoming": 0},
        )
        self.assertEqual(home["recent_bills"], [])
        self.assertEqual(home["pay_panel"]["items"], [])

        # My vendor is mine to see. The 777.00 on it is not.
        self.assertEqual(
            [
                (row["name"], row["monthly_amount"])
                for row in home["vendors_preview"]
            ],
            [("Mine", "0.00")],
        )

    def test_empty_account_returns_zeros_and_empty_lists_not_nulls(self):
        with self.assertNumQueries(EXPECTED_QUERIES):
            response = self.client.get(HOME_URL)

        home = response.data["data"]

        self.assertEqual(home["greeting"]["name"], "")
        self.assertEqual(home["stats"]["due_this_month"], "0.00")
        self.assertEqual(home["stats"]["total_bills"], 0)
        self.assertEqual(home["stats"]["paid"], 0)
        self.assertEqual(
            home["pay_panel"]["tabs"],
            {"overdue": 0, "due": 0, "upcoming": 0},
        )
        self.assertEqual(home["pay_panel"]["active_tab"], "overdue")
        self.assertEqual(home["recent_bills"], [])
        self.assertEqual(home["vendors_preview"], [])
        self.assertEqual(home["pay_panel"]["items"], [])

    def test_home_requires_authentication(self):
        response = APIClient().get(HOME_URL)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class HomePayloadShapeTests(HomeTestCase):
    """The wire format, key by key.

    The bill rows are a superset of the epic's sketch — ``vendor_name`` and
    ``vendor_logo`` rather than ``vendor``/``logo``, plus ``id``, plus
    ``pay_panel.active_tab``. That is a recorded deviation (see the "Shipped
    shape" note under E8-S1 in the epic), and a recorded deviation is only safe
    if the exact key set is asserted somewhere: otherwise the epic text and the
    wire drift, and the client is written against whichever one the developer
    happened to read.
    """

    ROW_KEYS = {
        "id",
        "bill_id",
        "vendor_id",
        "vendor_name",
        "vendor_logo",
        "category_name",
        "due_date",
        "amount",
        "status",
        "autopay_mode",
    }

    def test_the_payload_has_exactly_the_epics_five_sections(self):
        home = self._home()

        self.assertEqual(
            set(home),
            {
                "greeting",
                "stats",
                "recent_bills",
                "vendors_preview",
                "pay_panel",
            },
        )
        self.assertEqual(set(home["greeting"]), {"name"})
        self.assertEqual(
            set(home["stats"]), {"due_this_month", "total_bills", "paid"}
        )
        self.assertEqual(
            set(home["pay_panel"]), {"active_tab", "tabs", "items"}
        )
        self.assertEqual(
            set(home["pay_panel"]["tabs"]), {"overdue", "due", "upcoming"}
        )

    def test_bill_rows_are_occurrence_rows_not_the_epics_five_keys(self):
        bill = self._bill()
        self._occurrence(self._days(-1), bill=bill)

        home = self._home()
        rows = [home["recent_bills"][0], home["pay_panel"]["items"][0]]

        for row in rows:
            self.assertEqual(set(row), self.ROW_KEYS)
            # The sketch's spellings are absent, not merely supplemented — a
            # client reading row["vendor"] gets a KeyError, so this is the
            # assertion that has to be revisited if the deviation is rejected.
            self.assertNotIn("vendor", row)
            self.assertNotIn("logo", row)

    def test_vendor_preview_rows_carry_the_epics_keys(self):
        self._vendor(name="Acme")

        row = self._home()["vendors_preview"][0]

        self.assertEqual(
            set(row),
            {"id", "name", "logo", "category", "monthly_amount", "rail"},
        )

    def test_greeting_is_the_first_name_the_screen_renders(self):
        """The header reads "Welcome Back, {name}", so name is "Jhon"."""
        self.user.first_name = "Jhon"
        self.user.last_name = "Doe"
        self.user.save(update_fields=["first_name", "last_name"])

        self.assertEqual(self._home()["greeting"]["name"], "Jhon")

    def test_greeting_falls_back_to_the_full_name_without_a_first_name(self):
        self.user.last_name = "Doe"
        self.user.save(update_fields=["last_name"])

        self.assertEqual(self._home()["greeting"]["name"], "Doe")


class FixtureCalendarTests(HomeTestCase):
    """The date fixtures have to build on every day of the calendar.

    A bill cannot carry two occurrences on one due_date
    (uniq_occurrence_per_due_date), and these fixtures deliberately mix
    month-anchored dates with today-relative ones on a single bill. Spelled as
    fixed day numbers the two coincide on 48 days of the year, so the suite is
    green today and red on the 1st of next month — the worst kind of failure,
    because nothing changed. These are the days that used to break.
    """

    RISKY_DAYS = (
        dt.date(2026, 8, 1),
        dt.date(2026, 8, 2),
        dt.date(2026, 8, 3),
        dt.date(2026, 8, 4),
        dt.date(2026, 8, 5),
        dt.date(2026, 8, 31),
        dt.date(2026, 2, 1),
        dt.date(2026, 2, 28),
        dt.date(2026, 3, 1),
        dt.date(2026, 3, 3),
    )

    def test_the_mixed_month_fixture_builds_on_every_risky_day(self):
        for today in self.RISKY_DAYS:
            with self.subTest(today=today):
                self.today = today

                bill = self._seed_mixed_month()

                # Seven distinct due dates, so seven rows: fewer would mean a
                # collision, and a collision is an IntegrityError, not a
                # silently short fixture.
                self.assertEqual(bill.occurrences.count(), 7)

    def test_the_deletable_bill_fixture_builds_on_every_risky_day(self):
        for today in self.RISKY_DAYS:
            with self.subTest(today=today):
                self.today = today

                bill, occurrences = self._seed_deletable_bill()

                self.assertEqual(bill.occurrences.count(), len(occurrences))
                self.assertEqual(
                    len({row.due_date for row in occurrences}),
                    len(occurrences),
                )


class _PinnedClockMixin:
    """Runs an inherited suite with the Eastern clock parked on a fixed day.

    ``today_eastern()`` reads ``timezone.now()``, so patching that one function
    moves every date the endpoints and the fixtures compute, together.
    """

    PINNED_NOW = None

    def setUp(self):
        patcher = patch(
            "django.utils.timezone.now", return_value=self.PINNED_NOW
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        super().setUp()


class MonthStartReconciliationTests(
    _PinnedClockMixin, HomeReconciliationTests
):
    """Every reconciliation proof again, on the 1st of the month.

    16:00 UTC is noon Eastern on 1 September 2026 — the day on which "day 1 of
    this month" and "today" are the same date. That is where the fixtures used
    to raise IntegrityError and where a month-window off-by-one would show.
    """

    PINNED_NOW = dt.datetime(2026, 9, 1, 16, 0, tzinfo=dt.timezone.utc)


class MonthStartIsolationTests(_PinnedClockMixin, HomeIsolationTests):
    PINNED_NOW = dt.datetime(2026, 9, 1, 16, 0, tzinfo=dt.timezone.utc)


class MonthThirdIsolationTests(_PinnedClockMixin, HomeIsolationTests):
    """The 3rd: "today - 2" is day 1, the other date the fixture used to reuse."""

    PINNED_NOW = dt.datetime(2026, 9, 3, 16, 0, tzinfo=dt.timezone.utc)
