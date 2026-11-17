"""Starting a plan through Stripe Checkout (Phase 1).

The backend picks the route: a trial starts with no Stripe page, anything
payable goes to Stripe's hosted page, and the Swayp subscription appears
exactly once when that page is paid, whether the webhook or the success
page's poll gets there first.
"""

import json
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.billing.models import (
    CheckoutSession,
    CheckoutStatus,
    PlanCode,
    Subscription,
    SubscriptionStatus,
)
from apps.billing.services.checkout_service import (
    REDIRECT,
    SUBSCRIBED,
    CheckoutService,
)
from apps.billing.services.provider_service import BillingProviderService
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests.test_stripe_billing import CollectingStub
from apps.vendors.factories import UserFactory
from integrations.subscription_billing.base import CheckoutSessionRef


class CheckoutStub(CollectingStub):
    """Stripe's side: a session opens, then the test pays it."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.sessions = {}

    def create_checkout_session(self, *, customer_id, price_id, success_url,
                                cancel_url, metadata, idempotency_key=""):
        self._record(
            "create_checkout_session",
            price_id=price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
        )
        sid = f"cs_test_{len(self.sessions) + 1}"
        self.sessions[sid] = CheckoutSessionRef(
            id=sid,
            url=f"https://checkout.stripe.com/c/pay/{sid}",
            status="open",
            expires_at=4102444800,
        )

        return self.sessions[sid]

    def get_checkout_session(self, *, session_id):
        return self.sessions[session_id]

    def pay(self, sid):
        self.sessions[sid] = CheckoutSessionRef(
            id=sid, url="", status="complete", subscription_id=f"sub_{sid}"
        )


class CheckoutTestCase(TestCase):

    def setUp(self):
        self.stub = CheckoutStub()
        self.provider = BillingProviderService(provider=self.stub)
        self.subscriptions = SubscriptionService()
        self.subscriptions._provider = lambda: self.provider
        self.service = CheckoutService(
            subscriptions=self.subscriptions, provider=self.provider
        )
        self.account = UserFactory(is_active=True, is_verified=True)

    def start(self, code, account=None):
        return self.service.start(
            account=account or self.account, plan_code=code
        )


class RouteTests(CheckoutTestCase):

    def test_a_trial_starts_with_no_stripe_page(self):
        action, subscription = self.start(PlanCode.STANDARD)

        self.assertEqual(action, SUBSCRIBED)
        self.assertIsNotNone(subscription.trial_end)
        self.assertFalse(
            any(n == "create_checkout_session" for n, _ in self.stub.calls)
        )

    def test_founding_goes_to_stripe(self):
        action, session = self.start(PlanCode.FOUNDING)

        self.assertEqual(action, REDIRECT)
        self.assertTrue(session.url.startswith("https://checkout.stripe.com/"))
        self.assertFalse(Subscription.objects.filter(account=self.account).exists())

    def test_a_returning_account_pays_for_standard(self):
        """No second trial, whatever the button said."""
        Subscription.objects.create(
            account=self.account,
            plan=self.subscriptions.get_plan(PlanCode.STANDARD),
            status=SubscriptionStatus.CANCELLED,
            period_start="2026-01-01",
            period_end="2026-02-01",
        )

        action, _ = self.start(PlanCode.STANDARD)

        self.assertEqual(action, REDIRECT)

    def test_the_session_names_the_account_and_the_return_pages(self):
        self.start(PlanCode.FOUNDING)

        call = next(kw for n, kw in self.stub.calls if n == "create_checkout_session")
        self.assertEqual(call["metadata"]["account_id"], self.account.pk)
        self.assertIn("{CHECKOUT_SESSION_ID}", call["success_url"])
        self.assertTrue(call["cancel_url"].endswith("/pricing?plan=FOUNDING"))

    def test_a_second_click_reuses_the_open_page(self):
        _, first = self.start(PlanCode.FOUNDING)
        _, second = self.start(PlanCode.FOUNDING)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(CheckoutSession.objects.count(), 1)

    def test_refused_when_already_subscribed(self):
        self.start(PlanCode.STANDARD)

        with self.assertRaises(Exception) as caught:
            self.start(PlanCode.FOUNDING)

        self.assertIn("already_subscribed", str(caught.exception.get_codes()))


class FulfilmentTests(CheckoutTestCase):

    def paid_session(self, code=PlanCode.FOUNDING):
        _, session = self.start(code)
        self.stub.pay(session.provider_session_id)

        return session.provider_session_id

    def test_unpaid_creates_nothing(self):
        _, session = self.start(PlanCode.FOUNDING)

        self.assertIsNone(self.service.fulfil(session.provider_session_id))
        self.assertFalse(Subscription.objects.exists())

    def test_paid_creates_one_live_subscription(self):
        sid = self.paid_session()

        subscription = self.service.fulfil(sid)

        self.assertEqual(subscription.plan.code, PlanCode.FOUNDING)
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        self.assertEqual(subscription.provider_subscription_id, f"sub_{sid}")
        self.assertIsNone(subscription.trial_end)
        self.assertEqual(
            CheckoutSession.objects.get().status, CheckoutStatus.COMPLETE
        )

    def test_webhook_and_poll_leave_exactly_one(self):
        sid = self.paid_session()

        self.service.fulfil(sid)
        self.service.fulfil(sid)
        self.service.status(account=self.account, session_id=sid)

        self.assertEqual(Subscription.objects.count(), 1)

    def test_the_founding_spot_is_claimed_when_paid(self):
        sid = self.paid_session()

        with mock.patch(
            "apps.billing.services.subscription_service.FOUNDING_LOCK_LIMIT", 0
        ):
            subscription = self.service.fulfil(sid)

        self.assertIsNone(subscription.locked_price)

    def test_founding_paid_with_spots_left_is_locked(self):
        subscription = self.service.fulfil(self.paid_session())

        self.assertIsNotNone(subscription.locked_price)
        self.assertIsNotNone(subscription.founding_claimed_at)

    def test_two_paid_tabs_make_one_subscription(self):
        first = self.paid_session(PlanCode.FOUNDING)
        _, other = self.start(PlanCode.ENTERPRISE)
        self.stub.pay(other.provider_session_id)

        self.service.fulfil(first)
        self.service.fulfil(other.provider_session_id)

        self.assertEqual(
            Subscription.objects.filter(account=self.account).count(), 1
        )

    def test_another_accounts_session_is_not_found(self):
        sid = self.paid_session()

        with self.assertRaises(Exception):
            self.service.status(account=UserFactory(), session_id=sid)


@override_settings(STRIPE_BILLING_WEBHOOK_SECRET="whsec_test_secret")
class CheckoutWebhookTests(CheckoutTestCase):

    def post(self, event):
        from apps.billing.tests.test_stripe_billing import BillingWebhookTests

        return BillingWebhookTests.post(self, event)

    def event(self, type_, obj):
        return {
            "id": f"evt_{type_}",
            "object": "event",
            "type": type_,
            "data": {"object": obj},
        }

    def test_completed_fulfils(self):
        _, session = self.start(PlanCode.FOUNDING)
        sid = session.provider_session_id
        self.stub.pay(sid)

        with mock.patch(
            "apps.billing.services.checkout_service.BillingProviderService",
            return_value=self.provider,
        ):
            response = self.post(
                self.event("checkout.session.completed", {"id": sid})
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["handled"])
        self.assertEqual(Subscription.objects.filter(account=self.account).count(), 1)

    def test_expired_marks_the_row(self):
        _, session = self.start(PlanCode.FOUNDING)

        response = self.post(
            self.event(
                "checkout.session.expired", {"id": session.provider_session_id}
            )
        )
        self.assertEqual(response.status_code, 200, response.content[:2000])

        session.refresh_from_db()
        self.assertEqual(session.status, CheckoutStatus.EXPIRED)


class MockProviderTests(TestCase):
    """Local development: no Stripe, and the round trip still works."""

    def test_the_mock_completes_at_once(self):
        client = APIClient()
        account = UserFactory(is_active=True, is_verified=True)
        client.force_authenticate(user=account)

        response = client.post(
            "/api/v1/billing/checkout-session",
            {"plan": "FOUNDING"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        data = response.json()["data"]
        self.assertEqual(data["action"], "redirect")
        self.assertIn("/billing/success?session_id=", data["url"])

        status = client.get(
            f"/api/v1/billing/checkout-session/{data['session_id']}"
        ).json()["data"]
        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["subscription"]["plan"]["code"], "FOUNDING")

    def test_a_trial_answers_subscribed(self):
        client = APIClient()
        client.force_authenticate(user=UserFactory(is_active=True, is_verified=True))

        response = client.post(
            "/api/v1/billing/checkout-session",
            {"plan": "STANDARD"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.json()["data"]["action"], "subscribed")
        self.assertIsNone(response.json()["data"]["url"])
