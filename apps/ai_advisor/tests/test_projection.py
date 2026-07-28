"""E7-S3 — the balance projection, exact to the cent.

The three regressions guarded here are the ones that made the projection wrong
in opposite directions at once: bills invisible past E4's materialisation
horizon (overstates funds), and committed money invisible because an occurrence
goes SCHEDULED before the payment executes (also overstates funds).
"""

import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.ai_advisor.services.projection_service import ProjectionService
from apps.banking.factories import BankAccountFactory, UserFactory
from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.bills.services.bill_occurrence_service import BillOccurrenceService
from apps.common.enums import (
    BillFrequency,
    BillOccurrenceStatus,
    PaymentStatus,
)
from apps.payments.factories import PaymentFactory

PROJECTION_URL = "/api/v1/ai/balance-projection/"


class ProjectionServiceTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.today = timezone.localdate()
        self.account = BankAccountFactory(
            connection__user=self.user,
            available_balance=Decimal("10000.00"),
            balance_as_of=timezone.now(),
        )

    def _project(self, days):
        return ProjectionService().project(
            user=self.user,
            account_id=self.account.id,
            target_date=self.today + dt.timedelta(days=days),
        )

    def _bill(self, *, amount, frequency, in_days):
        return BillFactory(
            user=self.user,
            amount=Decimal(amount),
            frequency=frequency,
            anchor_date=self.today + dt.timedelta(days=in_days),
        )

    def test_matches_the_expected_projection_to_the_cent(self):
        bill = self._bill(
            amount="3200.00", frequency=BillFrequency.MONTHLY, in_days=3
        )
        BillOccurrenceFactory(
            bill=bill,
            due_date=self.today + dt.timedelta(days=3),
            amount=Decimal("3200.00"),
        )

        result = self._project(10)

        self.assertEqual(result["current_balance"], Decimal("10000.00"))
        self.assertEqual(result["outflow_total"], Decimal("3200.00"))
        self.assertEqual(result["committed_total"], Decimal("0.00"))
        self.assertEqual(result["projected_balance"], Decimal("6800.00"))
        self.assertTrue(result["sufficient"])

    def test_a_repriced_occurrence_wins_over_the_bill_amount(self):
        bill = self._bill(
            amount="3200.00", frequency=BillFrequency.MONTHLY, in_days=3
        )
        BillOccurrenceFactory(
            bill=bill,
            due_date=self.today + dt.timedelta(days=3),
            amount=Decimal("2750.55"),
        )

        self.assertEqual(self._project(10)["outflow_total"], Decimal("2750.55"))

    def test_weekly_bill_is_subtracted_past_e4s_materialisation_horizon(self):
        """E4 pre-creates two cycles — ~13 days for a weekly bill.

        Summing materialised rows alone therefore subtracts nothing beyond
        that and reports a comfortable surplus, more wrongly the further out
        the question is asked.
        """
        bill = self._bill(
            amount="100.00", frequency=BillFrequency.WEEKLY, in_days=1
        )

        # Exactly what the nightly beat job would have created, nothing more.
        BillOccurrenceService().generate_occurrences(bill, today=self.today)
        self.assertEqual(bill.occurrences.count(), 3)

        # Due dates are anchor + 0,7,...,49 => 8 of them inside 56 days.
        result = self._project(56)

        self.assertEqual(result["outflow_total"], Decimal("800.00"))
        self.assertEqual(result["projected_balance"], Decimal("9200.00"))

    def test_paid_occurrences_are_not_subtracted_again(self):
        bill = self._bill(
            amount="500.00", frequency=BillFrequency.ONE_TIME, in_days=2
        )
        BillOccurrenceFactory(
            bill=bill,
            due_date=self.today + dt.timedelta(days=2),
            amount=Decimal("500.00"),
            status=BillOccurrenceStatus.PAID,
        )

        self.assertEqual(self._project(10)["outflow_total"], Decimal("0.00"))

    def test_scheduled_occurrence_with_a_live_payment_is_counted_once(self):
        """An occurrence flips to SCHEDULED at payment *creation*.

        The money has not moved, so it belongs in the projection — but through
        the payment, not the bill, or it lands twice.
        """
        bill = self._bill(
            amount="3200.00", frequency=BillFrequency.ONE_TIME, in_days=3
        )
        occurrence = BillOccurrenceFactory(
            bill=bill,
            due_date=self.today + dt.timedelta(days=3),
            amount=Decimal("3200.00"),
            status=BillOccurrenceStatus.SCHEDULED,
        )
        PaymentFactory(
            user=self.user,
            funding_account=self.account,
            bill_occurrence=occurrence,
            amount="3200.00",
            total="3200.00",
            status=PaymentStatus.SCHEDULED,
            scheduled_for=self.today + dt.timedelta(days=1),
        )

        result = self._project(10)

        self.assertEqual(result["outflow_total"], Decimal("0.00"))
        self.assertEqual(result["committed_total"], Decimal("3200.00"))
        self.assertEqual(result["projected_balance"], Decimal("6800.00"))

    def test_scheduled_occurrence_with_no_payment_is_still_owed(self):
        bill = self._bill(
            amount="3200.00", frequency=BillFrequency.ONE_TIME, in_days=3
        )
        BillOccurrenceFactory(
            bill=bill,
            due_date=self.today + dt.timedelta(days=3),
            amount=Decimal("3200.00"),
            status=BillOccurrenceStatus.SCHEDULED,
        )

        self.assertEqual(self._project(10)["outflow_total"], Decimal("3200.00"))

    def test_ad_hoc_payment_with_no_occurrence_is_subtracted(self):
        PaymentFactory(
            user=self.user,
            funding_account=self.account,
            bill_occurrence=None,
            amount="500.00",
            total="500.00",
            status=PaymentStatus.PENDING,
            scheduled_for=None,
        )

        result = self._project(10)

        self.assertEqual(result["committed_total"], Decimal("500.00"))
        self.assertEqual(result["projected_balance"], Decimal("9500.00"))

    def test_settled_payment_is_not_subtracted_again(self):
        # The bank's balance already reflects it.
        PaymentFactory(
            user=self.user,
            funding_account=self.account,
            amount="500.00",
            total="500.00",
            status=PaymentStatus.SUCCESSFUL,
        )

        self.assertEqual(self._project(10)["committed_total"], Decimal("0.00"))

    def test_payment_scheduled_after_the_target_date_is_not_counted(self):
        PaymentFactory(
            user=self.user,
            funding_account=self.account,
            amount="500.00",
            total="500.00",
            status=PaymentStatus.SCHEDULED,
            scheduled_for=self.today + dt.timedelta(days=20),
        )

        self.assertEqual(self._project(10)["committed_total"], Decimal("0.00"))

    def test_payment_from_another_account_is_not_counted(self):
        other = BankAccountFactory(
            connection__user=self.user,
            available_balance=Decimal("500.00"),
            balance_as_of=timezone.now(),
            is_default_funding_source=False,
        )
        PaymentFactory(
            user=self.user,
            funding_account=other,
            amount="500.00",
            total="500.00",
            status=PaymentStatus.PENDING,
        )

        self.assertEqual(self._project(10)["committed_total"], Decimal("0.00"))

    def test_a_deleted_bill_drops_out_of_the_projection(self):
        bill = self._bill(
            amount="500.00", frequency=BillFrequency.ONE_TIME, in_days=2
        )
        BillOccurrenceFactory(
            bill=bill,
            due_date=self.today + dt.timedelta(days=2),
            amount=Decimal("500.00"),
        )
        bill.deleted_at = timezone.now()
        bill.save(update_fields=["deleted_at"])

        self.assertEqual(self._project(10)["outflow_total"], Decimal("0.00"))

    def test_insufficient_funds_are_reported(self):
        bill = self._bill(
            amount="12000.00", frequency=BillFrequency.ONE_TIME, in_days=2
        )
        BillOccurrenceFactory(
            bill=bill,
            due_date=self.today + dt.timedelta(days=2),
            amount=Decimal("12000.00"),
        )

        result = self._project(10)

        self.assertEqual(result["projected_balance"], Decimal("-2000.00"))
        self.assertFalse(result["sufficient"])


class ProjectionAPITests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.today = timezone.localdate()
        self.account = BankAccountFactory(
            connection__user=self.user,
            available_balance=Decimal("10000.00"),
            balance_as_of=timezone.now(),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _get(self, account_id, date):
        return self.client.get(
            PROJECTION_URL, {"account": str(account_id), "date": date.isoformat()}
        )

    def test_returns_the_projection(self):
        response = self._get(self.account.id, self.today + dt.timedelta(days=5))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["projected_balance"], "10000.00")
        self.assertIsNotNone(response.data["balance_as_of"])

    def test_past_date_is_unprocessable(self):
        response = self._get(self.account.id, self.today - dt.timedelta(days=1))

        self.assertEqual(
            response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY
        )

    def test_date_beyond_the_cap_is_unprocessable(self):
        response = self._get(self.account.id, self.today + dt.timedelta(days=1000))

        self.assertEqual(
            response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY
        )

    def test_foreign_account_is_not_found(self):
        stranger = BankAccountFactory(
            available_balance=Decimal("999.00"), balance_as_of=timezone.now()
        )

        response = self._get(stranger.id, self.today + dt.timedelta(days=5))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_requires_authentication(self):
        response = APIClient().get(PROJECTION_URL)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
