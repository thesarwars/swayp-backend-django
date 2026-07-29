"""One calendar day for every read path (E8-S1).

``TIME_ZONE`` is UTC, so between 19:00/20:00 ET and midnight
``timezone.localdate()`` already answers *tomorrow*. Every read that classifies
an occurrence therefore has to ask ``today_eastern()`` instead, and — this is
the part the reconciliation tests cannot prove — it has to do so *by default*,
because the shipped callers pass no ``today``: ``BillService.list_occurrences``,
``BillOccurrenceService.get_summary``, ``BillDetailSerializer`` and
``VendorListSerializer`` all rely on the default.

Comparing two endpoints to each other cannot catch a regression here: they
share the default, so they agree whether it is Eastern or UTC. These tests pin
the classification itself at an instant where the two calendars disagree, which
is the only way the default is actually asserted. They fail the moment any of
these paths goes back to ``localdate()``.
"""

import datetime as dt
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.banking.selectors.onboarding_selector import OnboardingSelector
from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.bills.selectors.bill_occurrence_selector import (
    BillOccurrenceSelector,
)
from apps.common.dates import today_eastern
from apps.common.enums import BillOccurrenceStatus
from apps.vendors.factories import (
    BillCategoryFactory,
    UserFactory,
    VendorFactory,
)
from apps.vendors.selectors.vendor_selector import VendorSelector

#: 21:30 on the user's clock; already tomorrow in UTC. The whole point of the
#: module is that these two dates differ.
EASTERN_DAY = dt.date(2026, 7, 29)
PINNED_NOW = dt.datetime(2026, 7, 30, 1, 30, tzinfo=dt.timezone.utc)

BILLS_SUMMARY_URL = "/api/v1/bills/summary/"
OCCURRENCES_URL = "/api/v1/bills/occurrences/"
NEXT_DUE_URL = "/api/v1/bills/next-due/"
VENDORS_URL = "/api/v1/vendors/"
ONBOARDING_SUMMARY_URL = "/api/v1/banking/onboarding-summary/"
HOME_URL = "/api/v1/dashboard/home/"


class EasternEveningTests(TestCase):
    """An occurrence due today-on-the-user's-clock is DUE, never OVERDUE."""

    def setUp(self):
        patcher = patch("django.utils.timezone.now", return_value=PINNED_NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.user = UserFactory()
        category = BillCategoryFactory()
        self.vendor = VendorFactory(
            user=self.user, category=category, name="Acme"
        )
        self.bill = BillFactory(
            user=self.user,
            vendor=self.vendor,
            category=category,
            amount=Decimal("500.00"),
            anchor_date=EASTERN_DAY,
        )
        self.occurrence = BillOccurrenceFactory(
            bill=self.bill,
            due_date=EASTERN_DAY,
            amount=Decimal("500.00"),
            status=BillOccurrenceStatus.UPCOMING,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_the_two_calendars_disagree_at_this_instant(self):
        """Guard on the guard: without this the rest proves nothing.

        If TIME_ZONE ever becomes Eastern, or the pinned instant drifts out of
        the evening window, every assertion below would pass under a UTC
        default too and the module would go quietly vacuous.
        """
        self.assertEqual(today_eastern(), EASTERN_DAY)
        self.assertEqual(timezone.localdate(), dt.date(2026, 7, 30))
        self.assertNotEqual(today_eastern(), timezone.localdate())

    def test_selector_summary_default_classifies_on_the_eastern_day(self):
        # No `today` argument — this is the default under test.
        summary = BillOccurrenceSelector().get_summary(self.user)

        self.assertEqual(summary["due_count"], 1)
        self.assertEqual(summary["overdue_count"], 0)
        self.assertEqual(summary["upcoming_count"], 0)
        self.assertEqual(summary["total_due_this_month"], Decimal("500.00"))

    def test_bills_summary_endpoint_classifies_on_the_eastern_day(self):
        response = self.client.get(BILLS_SUMMARY_URL)
        data = response.data["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data["due_count"], 1)
        self.assertEqual(data["overdue_count"], 0)
        self.assertEqual(data["total_due_this_month"], "500.00")

    def test_occurrence_list_row_is_due_not_overdue(self):
        response = self.client.get(OCCURRENCES_URL)

        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["status"], "DUE")

    def test_next_due_still_sees_an_occurrence_due_today(self):
        response = self.client.get(NEXT_DUE_URL)

        self.assertEqual(
            response.data["data"]["due_date"], EASTERN_DAY.isoformat()
        )

    def test_bill_detail_does_not_call_it_a_day_late(self):
        response = self.client.get(
            f"/api/v1/bills/{self.bill.id}/details/"
        )
        data = response.data["data"]

        self.assertEqual(data["next_due"], EASTERN_DAY)
        self.assertEqual(Decimal(str(data["overdue_amount"])), Decimal("0"))
        self.assertEqual(data["days_overdue"], 0)

    def test_vendor_row_still_shows_the_occurrence_as_next_due(self):
        response = self.client.get(VENDORS_URL)
        row = response.data["items"][0]

        self.assertEqual(row["name"], "Acme")
        self.assertEqual(row["next_due"], EASTERN_DAY)
        self.assertEqual(row["recurring_amount"], Decimal("500.00"))
        # The selector behind it, with no `today` passed.
        self.assertEqual(
            VendorSelector.next_bill(self.vendor).due_date, EASTERN_DAY
        )

    def test_onboarding_summary_cannot_contradict_bills_summary(self):
        """docs/banking-api-documentation.md: the two "cannot disagree"."""
        bills = self.client.get(BILLS_SUMMARY_URL).data["data"]
        onboarding = self.client.get(ONBOARDING_SUMMARY_URL).data["data"]

        self.assertEqual(
            onboarding["bills"],
            {
                "total_due_this_month": Decimal(
                    bills["total_due_this_month"]
                ),
                "overdue_count": bills["overdue_count"],
                "due_count": bills["due_count"],
                "upcoming_count": bills["upcoming_count"],
            },
        )
        self.assertEqual(onboarding["bills"]["due_count"], 1)
        # And the selector default, not just the endpoint.
        self.assertEqual(
            OnboardingSelector().summary(self.user)["bills"]["overdue_count"],
            0,
        )

    def test_dashboard_home_agrees_with_all_of_them(self):
        home = self.client.get(HOME_URL).data["data"]

        self.assertEqual(
            home["pay_panel"]["tabs"],
            {"overdue": 0, "due": 1, "upcoming": 0},
        )
        self.assertEqual(home["stats"]["due_this_month"], "500.00")
        self.assertEqual(home["pay_panel"]["active_tab"], "due")


class EasternMonthEndTests(TestCase):
    """The month window is Eastern too, not just the day boundary."""

    #: 21:00 ET on 31 July; 1 August in UTC.
    PINNED_NOW = dt.datetime(2026, 8, 1, 1, 0, tzinfo=dt.timezone.utc)

    def setUp(self):
        patcher = patch(
            "django.utils.timezone.now", return_value=self.PINNED_NOW
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.user = UserFactory()
        category = BillCategoryFactory()
        vendor = VendorFactory(user=self.user, category=category)
        bill = BillFactory(
            user=self.user,
            vendor=vendor,
            category=category,
            anchor_date=dt.date(2026, 7, 31),
        )

        # July on the user's clock, August in UTC.
        BillOccurrenceFactory(
            bill=bill, due_date=dt.date(2026, 7, 31), amount=Decimal("600.00")
        )
        BillOccurrenceFactory(
            bill=bill, due_date=dt.date(2026, 8, 1), amount=Decimal("700.00")
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_due_this_month_is_the_eastern_month(self):
        self.assertEqual(today_eastern(), dt.date(2026, 7, 31))
        self.assertEqual(timezone.localdate(), dt.date(2026, 8, 1))

        summary = self.client.get(BILLS_SUMMARY_URL).data["data"]

        # 600 (31 July) is this month; 700 (1 Aug) is next month and upcoming.
        self.assertEqual(summary["total_due_this_month"], "600.00")
        self.assertEqual(summary["due_count"], 1)
        self.assertEqual(summary["upcoming_count"], 1)
        self.assertEqual(summary["overdue_count"], 0)

        onboarding = self.client.get(ONBOARDING_SUMMARY_URL).data["data"]

        self.assertEqual(
            onboarding["bills"]["total_due_this_month"], Decimal("600.00")
        )
        self.assertEqual(onboarding["bills"]["overdue_count"], 0)
