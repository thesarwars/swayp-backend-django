"""The mobile team's billing change requests (BILLING-1 … BILLING-11)."""

import datetime as dt

from django.test import TestCase
from rest_framework.test import APIClient

from apps.billing.factories import SubscriptionFactory
from apps.billing.models import (
    Plan,
    PlanCode,
    Subscription,
    SubscriptionStatus,
)
from apps.billing.services.subscription_service import SubscriptionService
from apps.vendors.factories import UserFactory

D = dt.date


class BillingTestCase(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.service = SubscriptionService()

    def subscribe(self, plan=PlanCode.STANDARD, **kwargs):
        return self.service.subscribe(
            account=self.user, plan_code=plan, **kwargs
        )


class PastDueTests(BillingTestCase):
    """BILLING-6: a past-due subscription is still the account's plan."""

    def setUp(self):
        super().setUp()
        self.subscription = self.subscribe()
        self.subscription.status = SubscriptionStatus.PAST_DUE
        self.subscription.save(update_fields=["status"])

    def test_get_returns_it_flagged_past_due(self):
        data = self.client.get("/api/v1/billing/subscription").json()["data"]

        self.assertIsNotNone(data)
        self.assertEqual(data["status"], "PAST_DUE")
        self.assertTrue(data["past_due"])

    def test_it_still_counts_for_plan_limits(self):
        self.assertEqual(self.service.current(self.user), self.subscription)

    def test_a_second_subscription_is_refused(self):
        response = self.client.post(
            "/api/v1/billing/subscription",
            {"plan": PlanCode.FOUNDING},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Subscription.objects.filter(account=self.user).count(), 1)


class TrialEligibilityTests(BillingTestCase):
    """BILLING-4: one trial per account, and the plan list says so."""

    def plans(self):
        return {
            p["code"]: p
            for p in self.client.get("/api/v1/billing/plans").json()["data"]
        }

    def trial_plan(self):
        return next(
            code for code, p in self.plans().items() if p["trial_days"]
        )

    def test_a_new_account_is_offered_the_trial(self):
        code = self.trial_plan()

        self.assertTrue(self.plans()[code]["trial_eligible"])

    def test_resubscribing_after_cancel_gets_no_second_trial(self):
        code = self.trial_plan()
        first = self.subscribe(code)
        self.assertIsNotNone(first.trial_end)
        cancelled = self.service.cancel(account=self.user)
        self.service.end_if_due(cancelled, today=cancelled.cancels_on)

        second = self.subscribe(code)

        self.assertIsNone(second.trial_end)
        self.assertFalse(self.plans()[code]["trial_eligible"])

    def test_the_founding_lock_reports_spots_left(self):
        founding = self.plans()[PlanCode.FOUNDING]

        self.assertTrue(founding["lock_available"])
        self.assertGreater(founding["founding_spots_remaining"], 0)
        self.assertIsNone(self.plans()[PlanCode.STANDARD]["founding_spots_remaining"])


class CancelAtPeriodEndTests(BillingTestCase):
    """BILLING-5: cancelling keeps the paid period, and can be undone."""

    def setUp(self):
        super().setUp()
        self.subscription = self.subscribe(PlanCode.FOUNDING, today=D(2026, 8, 1))

    def test_cancel_keeps_the_plan_until_the_period_ends(self):
        response = self.client.delete("/api/v1/billing/subscription")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "ACTIVE")
        self.assertTrue(data["cancel_pending"])
        self.assertEqual(data["cancels_on"], "2026-09-01")
        self.assertEqual(self.service.current(self.user), self.subscription)

    def test_resume_withdraws_it(self):
        self.client.delete("/api/v1/billing/subscription")

        response = self.client.post("/api/v1/billing/subscription/resume")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["cancel_pending"])
        self.assertIsNone(response.json()["data"]["cancels_on"])

    def test_resume_without_a_pending_cancel_is_a_400(self):
        self.assertEqual(
            self.client.post("/api/v1/billing/subscription/resume").status_code,
            400,
        )

    def test_the_daily_job_ends_it_on_the_date(self):
        from unittest.mock import patch

        from apps.billing.tasks import renew_subscriptions

        self.client.delete("/api/v1/billing/subscription")

        with patch("django.utils.timezone.localdate", return_value=D(2026, 9, 1)):
            result = renew_subscriptions()

        self.subscription.refresh_from_db()
        self.assertEqual(result["ended"], 1)
        self.assertEqual(self.subscription.status, SubscriptionStatus.CANCELLED)

    def test_a_trial_cancel_ends_with_the_trial(self):
        account = UserFactory()
        trial_plan = Plan.objects.filter(trial_days__gt=0).first().code
        subscription = self.service.subscribe(
            account=account, plan_code=trial_plan, today=D(2026, 8, 1)
        )

        cancelled = self.service.cancel(account=account, today=D(2026, 8, 3))

        self.assertEqual(cancelled.cancels_on, subscription.trial_end)


class DowngradeBelowUsageTests(BillingTestCase):
    """BILLING-7: a plan too small for current usage is refused with 402."""

    def test_too_many_banks_for_the_target_plan(self):
        from apps.banking.factories import BankConnectionFactory

        self.subscribe(PlanCode.STANDARD)
        for _ in range(3):
            BankConnectionFactory(user=self.user)

        response = self.client.patch(
            "/api/v1/billing/subscription",
            {"plan": PlanCode.FOUNDING},
            format="json",
        )

        self.assertEqual(response.status_code, 402)
        self.assertIn("3 connected banks in use", response.json()["message"])
        self.assertEqual(response.json()["code"], "plan_limit")
        self.assertEqual(response.json()["limit"], "BANKS")
        self.assertEqual(
            self.service.current(self.user).plan.code, PlanCode.STANDARD
        )

    def test_a_downgrade_that_fits_goes_through(self):
        self.subscribe(PlanCode.STANDARD)

        response = self.client.patch(
            "/api/v1/billing/subscription",
            {"plan": PlanCode.FOUNDING},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    def test_changing_with_no_subscription_is_a_400(self):
        response = self.client.patch(
            "/api/v1/billing/subscription",
            {"plan": PlanCode.FOUNDING},
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class BillingConfigTests(BillingTestCase):
    """BILLING-3: collects_money without opening a SetupIntent."""

    def test_the_mock_collects_nothing_and_creates_nothing(self):
        from unittest.mock import patch

        with patch(
            "apps.billing.services.provider_service.BillingProviderService.create_setup_intent",
            side_effect=AssertionError("must not open a SetupIntent"),
            create=True,
        ):
            data = self.client.get("/api/v1/billing/config").json()["data"]

        self.assertEqual(data["collects_money"], False)
        self.assertEqual(data["publishable_key"], "")
        self.assertEqual(data["fees"], {
            "ach_standard": "0.00", "ach_same_day": "4.99",
            "network": "0.00", "check_standard": "0.00",
            "check_overage": "2.99", "check_expedited": "8.99",
        })

    def test_config_is_public(self):
        self.assertEqual(
            APIClient().get("/api/v1/billing/config").status_code, 200)


class FeeListTests(BillingTestCase):
    """BILLING-9: the fee ledger is paged, filterable and links to payments."""

    URL = "/api/v1/billing/fees"

    def setUp(self):
        super().setUp()
        from apps.billing.factories import FeeChargeFactory
        from apps.billing.models import FeeState
        from apps.payments.factories import PaymentFactory

        self.subscription = self.subscribe()

        def fee(state, day):
            charge = FeeChargeFactory(
                subscription=self.subscription,
                payment=PaymentFactory(user=self.user),
                state=state,
            )
            # created_at is auto_now_add; move it with an update.
            type(charge).objects.filter(pk=charge.pk).update(
                created_at=dt.datetime(
                    day.year, day.month, day.day, 12, tzinfo=dt.timezone.utc
                )
            )
            return charge

        self.pending = fee(FeeState.PENDING, D(2026, 9, 1))
        self.refunded = fee(FeeState.REFUNDED, D(2026, 9, 10))
        self.billed = fee(FeeState.BILLED, D(2026, 9, 20))

    def _ids(self, query=""):
        body = self.client.get(f"{self.URL}{query}").json()
        return [row["id"] for row in body["data"]], body

    def test_rows_carry_payment_id_and_the_list_is_paged(self):
        ids, body = self._ids("?page=1&pageSize=2")

        self.assertEqual(len(ids), 2)
        self.assertEqual(body["pagination"]["totalItems"], 3)
        self.assertTrue(body["pagination"]["hasNext"])
        self.assertEqual(
            body["data"][0]["payment_id"], str(self.billed.payment_id)
        )

    def test_state_filter(self):
        ids, _ = self._ids("?state=REFUNDED")

        self.assertEqual(ids, [str(self.refunded.id)])

    def test_date_range_is_inclusive(self):
        ids, _ = self._ids("?from_date=2026-09-01&to_date=2026-09-10")

        self.assertEqual(
            ids, [str(self.refunded.id), str(self.pending.id)]
        )

    def test_a_backwards_range_is_a_400(self):
        response = self.client.get(
            f"{self.URL}?from_date=2026-09-10&to_date=2026-09-01"
        )

        self.assertEqual(response.status_code, 400)

    def test_an_unknown_state_is_a_400(self):
        response = self.client.get(f"{self.URL}?state=LOST")

        self.assertEqual(response.status_code, 400)


class InvoiceLineTests(BillingTestCase):
    """BILLING-10: lines say what they are; the preview says when it bills."""

    URL = "/api/v1/billing/invoice"

    def _preview(self):
        return self.client.get(self.URL).json()["data"]

    def _collecting(self, collects=True):
        from unittest import mock

        from apps.billing.services.provider_service import (
            BillingProviderService,
        )

        return mock.patch.object(
            BillingProviderService, "collects_money",
            new_callable=mock.PropertyMock, return_value=collects,
        )

    def test_fee_lines_carry_state_ids_and_time(self):
        from apps.billing.factories import FeeChargeFactory
        from apps.billing.models import FeeState
        from apps.payments.factories import PaymentFactory

        subscription = self.subscribe()
        fee = FeeChargeFactory(
            subscription=subscription,
            payment=PaymentFactory(user=self.user),
            state=FeeState.REFUNDED,
        )

        plan_line, fee_line = self._preview()["lines"]

        self.assertIsNone(plan_line["state"])
        self.assertIsNone(plan_line["fee_charge_id"])
        self.assertEqual(fee_line["state"], "REFUNDED")
        self.assertEqual(fee_line["fee_charge_id"], str(fee.id))
        self.assertEqual(
            fee_line["payment_reference"], fee.payment.transaction_reference
        )
        self.assertIsNotNone(fee_line["created_at"])

    def test_next_charge_is_the_trial_end_during_a_trial(self):
        subscription = self.subscribe()
        self.assertIsNotNone(subscription.trial_end)

        with self._collecting():
            data = self._preview()

        self.assertEqual(data["next_charge_date"], str(subscription.trial_end))

    def test_next_charge_is_the_period_end_after_the_trial(self):
        subscription = self.subscribe()
        subscription.trial_end = None
        subscription.save(update_fields=["trial_end"])

        with self._collecting():
            data = self._preview()

        self.assertEqual(
            data["next_charge_date"], str(subscription.period_end)
        )

    def test_no_next_charge_when_cancelling(self):
        self.subscribe()
        self.service.cancel(account=self.user)

        with self._collecting():
            data = self._preview()

        self.assertIsNone(data["next_charge_date"])

    def test_no_next_charge_when_nothing_is_collected(self):
        self.subscribe()

        with self._collecting(False):
            data = self._preview()

        self.assertIsNone(data["next_charge_date"])


class ErrorCodeTests(BillingTestCase):
    """BILLING-11: 402 and a role's 403 say which, without parsing text."""

    def test_a_capacity_402_names_the_limit(self):
        from apps.billing.services.allowance_service import AllowanceService
        from apps.billing.models import AllowanceKind
        from apps.common.exception_handler import custom_exception_handler
        from apps.common.exceptions import PlanLimitExceededException

        subscription = self.subscribe(PlanCode.FOUNDING)
        limit = AllowanceService().limit_for(subscription, AllowanceKind.SEATS)

        with self.assertRaises(PlanLimitExceededException) as raised:
            AllowanceService().check_capacity(
                subscription=subscription,
                kind=AllowanceKind.SEATS,
                requested=limit + 1,
            )

        body = custom_exception_handler(raised.exception, {}).data
        self.assertEqual(body["code"], "plan_limit")
        self.assertEqual(body["limit"], "SEATS")
        self.assertFalse(body["success"])

    def test_a_role_403_names_the_capability(self):
        from apps.teams.factories import ActiveMemberFactory

        owner = UserFactory()
        self.service.subscribe(account=owner, plan_code=PlanCode.STANDARD)
        ActiveMemberFactory(account=owner, user=self.user)

        response = self.client.delete("/api/v1/billing/subscription")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "role_forbidden")
        self.assertEqual(response.json()["capability"], "manage_billing")

    def test_other_errors_carry_their_generic_code(self):
        response = self.client.patch(
            "/api/v1/billing/subscription",
            {"plan": PlanCode.FOUNDING},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "validation_failed")
        self.assertNotIn("limit", response.json())


class PlanDisplayTests(BillingTestCase):
    """BILLING-8: the pricing screen's copy comes from the server."""

    def _plans(self):
        return {
            row["code"]: row
            for row in self.client.get("/api/v1/billing/plans").json()["data"]
        }

    def test_every_plan_has_a_description_features_and_interval(self):
        for code, row in self._plans().items():
            with self.subTest(code=code):
                self.assertTrue(row["description"])
                self.assertTrue(row["features"])
                self.assertEqual(row["billing_interval"], "month")

    def test_features_follow_the_plans_limits(self):
        plans = self._plans()

        self.assertIn("Up to 3 team members", plans["FOUNDING"]["features"])
        self.assertIn("1 connected bank account", plans["FOUNDING"]["features"])
        self.assertIn(
            "2 physical checks a month included", plans["FOUNDING"]["features"]
        )
        self.assertIn(
            "Unlimited connected bank accounts", plans["STANDARD"]["features"]
        )
        self.assertIn("Up to 3 entities", plans["ENTERPRISE"]["features"])

    def test_a_changed_limit_changes_the_line(self):
        Plan.objects.filter(code=PlanCode.FOUNDING).update(seat_limit=4)

        self.assertIn(
            "Up to 4 team members", self._plans()["FOUNDING"]["features"]
        )


class PublicPlansTests(TestCase):
    """Web §4: the pricing page reads the plans without signing in."""

    def test_anonymous(self):
        response = APIClient().get("/api/v1/billing/plans")

        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        self.assertTrue(rows)
        standard = next(r for r in rows if r["code"] == "STANDARD")
        self.assertTrue(standard["trial_eligible"])

    def test_a_token_still_personalises_it(self):
        user = UserFactory()
        SubscriptionService().subscribe(account=user, plan_code="STANDARD")
        Subscription.objects.filter(account=user).update(
            status=SubscriptionStatus.CANCELLED)
        client = APIClient()
        client.force_authenticate(user=user)

        rows = client.get("/api/v1/billing/plans").json()["data"]
        standard = next(r for r in rows if r["code"] == "STANDARD")

        self.assertFalse(standard["trial_eligible"])
