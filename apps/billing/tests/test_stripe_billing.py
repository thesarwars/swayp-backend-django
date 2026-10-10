"""Subscription billing through a provider (E9-S1).

No network. The Stripe adapter is exercised against a fake SDK that returns
the shapes the real API returns — verified by running the real one against
test mode — because a suite that reaches a live payment processor is slow,
flaky, and leaves real customers behind.

The seam being tested is the important part: with the mock provider nothing is
charged and every pre-Stripe caller behaves exactly as before, and with a
collecting provider the same code paths link the two systems.
"""

import json
from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.billing.factories import SubscriptionFactory
from apps.billing.models import (
    FeeKind,
    Plan,
    PlanCode,
    Subscription,
    SubscriptionStatus,
)
from apps.billing.services.provider_service import (
    BillingProviderService,
    swayp_status,
)
from apps.billing.services.subscription_service import SubscriptionService
from apps.vendors.factories import UserFactory
from integrations.factory import get_subscription_billing_provider
from integrations.subscription_billing.base import (
    BillingProviderError,
    CardDeclined,
    CardRef,
    CustomerRef,
    SetupIntentRef,
    SubscriptionBillingProvider,
    SubscriptionRef,
)
from integrations.subscription_billing.mock import (
    MockSubscriptionBillingProvider,
)


def plan(code):
    return Plan.objects.get(code=code)


class CollectingStub(SubscriptionBillingProvider):
    """A provider that collects money, without a network."""

    name = "stub"
    collects_money = True

    def __init__(self, *, fail_with=None, status="active", secret="pi_x_secret"):
        self.fail_with = fail_with
        self.status = status
        self.secret = secret
        self.calls = []

    def _record(self, what, **kw):
        self.calls.append((what, kw))

        if self.fail_with is not None:
            raise self.fail_with

    def ensure_customer(self, *, account_id, email, name=""):
        self.calls.append(("ensure_customer", {"account_id": account_id}))

        return CustomerRef(id=f"cus_{account_id[:8]}")

    def ensure_price(self, *, plan_code, name, amount, currency="usd"):
        self.calls.append(("ensure_price", {"plan_code": plan_code}))

        return f"price_{plan_code.lower()}"

    def create_setup_intent(self, *, customer_id):
        return SetupIntentRef(
            client_secret="seti_x_secret", publishable_key="pk_stub"
        )

    def create_subscription(self, *, customer_id, price_id,
                            payment_method_id="", trial_days=0,
                            idempotency_key=""):
        self._record(
            "create_subscription",
            price_id=price_id,
            payment_method_id=payment_method_id,
            trial_days=trial_days,
            idempotency_key=idempotency_key,
        )

        return SubscriptionRef(
            id="sub_stub", status=self.status, client_secret=self.secret
        )

    def change_plan(self, *, subscription_id, price_id):
        self._record("change_plan", price_id=price_id)

        return SubscriptionRef(id=subscription_id, status=self.status)

    def cancel_subscription(self, *, subscription_id):
        self._record("cancel_subscription")

        return SubscriptionRef(id=subscription_id, status="canceled")

    def get_default_card(self, *, customer_id):
        self._record("get_default_card")

        return getattr(self, "card", None)

    def set_default_card(self, *, customer_id, payment_method_id,
                         subscription_id=""):
        self._record(
            "set_default_card",
            payment_method_id=payment_method_id,
            subscription_id=subscription_id,
        )

        return CardRef(brand="visa", last4="4242", exp_month=12, exp_year=2030)

    def retry_latest_invoice(self, *, subscription_id):
        self._record("retry_latest_invoice")

        return getattr(self, "retry_pays", True)

    def set_cancel_at_period_end(self, *, subscription_id, cancel):
        self._record("set_cancel_at_period_end", cancel=cancel)

        return SubscriptionRef(id=subscription_id, status=self.status)

    def add_invoice_item(self, *, customer_id, amount, description,
                         currency="usd", idempotency_key=""):
        self._record(
            "add_invoice_item", amount=amount, idempotency_key=idempotency_key
        )

        return "ii_stub"


class ProviderSelectionTests(TestCase):

    def test_the_suite_never_reaches_a_real_processor(self):
        """If this fails, every other test in the suite is calling Stripe."""
        provider = get_subscription_billing_provider()

        self.assertIsInstance(provider, MockSubscriptionBillingProvider)
        self.assertFalse(provider.collects_money)

    @override_settings(SUBSCRIPTION_BILLING_PROVIDER="stripe",
                       STRIPE_SECRET_KEY="")
    def test_selecting_stripe_without_a_key_says_so(self):
        with self.assertRaises(BillingProviderError) as ctx:
            get_subscription_billing_provider()

        self.assertIn("STRIPE_SECRET_KEY", str(ctx.exception))

    @override_settings(SUBSCRIPTION_BILLING_PROVIDER="paypal")
    def test_an_unknown_provider_is_refused_not_silently_mocked(self):
        with self.assertRaises(NotImplementedError):
            get_subscription_billing_provider()


class MockProviderTests(TestCase):
    """The default. Entitlement without collection."""

    def test_subscribing_charges_nothing_and_links_nothing(self):
        user = UserFactory()

        subscription = SubscriptionService().subscribe(
            account=user, plan_code=PlanCode.FOUNDING
        )

        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        self.assertEqual(subscription.provider_subscription_id, "")
        self.assertEqual(subscription.provider_customer_id, "")

    def test_a_payment_method_is_accepted_and_ignored(self):
        """So a client built for Stripe still works on a mock deployment."""
        user = UserFactory()

        subscription = SubscriptionService().subscribe(
            account=user,
            plan_code=PlanCode.FOUNDING,
            payment_method_id="pm_whatever",
        )

        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)

    def test_customer_ids_are_stable(self):
        provider = MockSubscriptionBillingProvider()

        first = provider.ensure_customer(account_id="a1", email="a@b.c")
        again = provider.ensure_customer(account_id="a1", email="a@b.c")

        self.assertEqual(first.id, again.id)

    def test_a_price_change_produces_a_new_price(self):
        provider = MockSubscriptionBillingProvider()

        cheap = provider.ensure_price(
            plan_code="FOUNDING", name="F", amount=Decimal("49.00")
        )
        dear = provider.ensure_price(
            plan_code="FOUNDING", name="F", amount=Decimal("59.00")
        )

        self.assertNotEqual(cheap, dear)


class CollectingProviderTests(TestCase):

    def setUp(self):
        self.stub = CollectingStub()
        self.subscription = SubscriptionFactory(plan=plan(PlanCode.FOUNDING))
        self.service = BillingProviderService(provider=self.stub)

    def test_starting_links_both_ids_to_the_row(self):
        self.service.start(self.subscription)
        self.subscription.refresh_from_db()

        self.assertTrue(self.subscription.provider_customer_id)
        self.assertEqual(
            self.subscription.provider_subscription_id, "sub_stub"
        )
        self.assertEqual(self.subscription.provider_status, "active")

    def test_the_idempotency_key_is_the_subscription(self):
        """A retried subscribe must not open a second one and bill twice."""
        self.service.start(self.subscription)

        call = next(
            kw for name, kw in self.stub.calls
            if name == "create_subscription"
        )
        self.assertEqual(
            call["idempotency_key"], f"sub:{self.subscription.pk}"
        )

    def test_the_customer_id_is_reused_not_recreated(self):
        self.service.customer_id(self.subscription)
        self.service.customer_id(self.subscription)

        created = [c for c in self.stub.calls if c[0] == "ensure_customer"]
        self.assertEqual(len(created), 1)

    def test_the_price_is_cached_on_the_plan(self):
        self.service.price_id(self.subscription.plan)
        self.service.price_id(self.subscription.plan)

        asked = [c for c in self.stub.calls if c[0] == "ensure_price"]
        self.assertEqual(len(asked), 1)

        self.subscription.plan.refresh_from_db()
        self.assertEqual(
            self.subscription.plan.provider_price_id, "price_founding"
        )

    def test_a_declined_card_is_a_field_error_not_a_402(self):
        """402 renders as "upgrade your plan", which is wrong when the plan
        is fine and the card is not."""
        from rest_framework.exceptions import ValidationError

        service = BillingProviderService(
            provider=CollectingStub(fail_with=CardDeclined("Card declined."))
        )

        with self.assertRaises(ValidationError) as ctx:
            service.start(self.subscription)

        self.assertIn("payment_method_id", ctx.exception.detail)

    def test_a_provider_outage_is_503_not_500(self):
        from apps.billing.services.provider_service import ServiceUnavailable

        service = BillingProviderService(
            provider=CollectingStub(fail_with=BillingProviderError("down"))
        )

        with self.assertRaises(ServiceUnavailable) as ctx:
            service.start(self.subscription)

        self.assertEqual(ctx.exception.status_code, 503)

    def test_cancel_never_blocks_the_swayp_side(self):
        """Telling a customer their cancellation failed while continuing to
        bill them is the one outcome worth avoiding at any cost."""
        self.service.start(self.subscription)

        broken = BillingProviderService(
            provider=CollectingStub(fail_with=BillingProviderError("down"))
        )

        # Does not raise.
        self.assertIsNone(broken.cancel(self.subscription))

    def test_a_cancelled_subscription_is_never_resurrected(self):
        self.service.start(self.subscription)

        self.subscription.status = SubscriptionStatus.CANCELLED
        self.subscription.save(update_fields=["status"])

        self.service.change_plan(self.subscription)
        self.subscription.refresh_from_db()

        self.assertEqual(
            self.subscription.status, SubscriptionStatus.CANCELLED
        )

    def test_a_fee_failure_never_breaks_the_payment(self):
        from apps.billing.models import FeeCharge
        from apps.payments.factories import PaymentFactory

        fee = FeeCharge.objects.create(
            subscription=self.subscription,
            payment=PaymentFactory(user=self.subscription.account),
            kind=FeeKind.SAME_DAY_ACH,
            amount=Decimal("4.99"),
        )
        self.service.start(self.subscription)
        self.subscription.refresh_from_db()

        broken = BillingProviderService(
            provider=CollectingStub(fail_with=BillingProviderError("down"))
        )

        # Swallowed: the ledger row is the record of truth.
        self.assertIsNone(broken.record_fee(fee))


class StatusMappingTests(TestCase):

    def test_incomplete_keeps_the_entitlement(self):
        """A 3-D Secure prompt is the bank's step, not a failure to pay."""
        self.assertEqual(swayp_status("incomplete"), "ACTIVE")

    def test_a_failed_charge_is_past_due_not_cancelled(self):
        self.assertEqual(swayp_status("past_due"), "PAST_DUE")
        self.assertEqual(swayp_status("unpaid"), "PAST_DUE")

    def test_cancelled_states_map_to_cancelled(self):
        self.assertEqual(swayp_status("canceled"), "CANCELLED")
        self.assertEqual(swayp_status("incomplete_expired"), "CANCELLED")

    def test_an_unknown_status_changes_nothing(self):
        self.assertIsNone(swayp_status("something_new"))


class StripeAdapterTests(TestCase):
    """The adapter against payload shapes captured from real test mode."""

    def adapter(self):
        from integrations.subscription_billing.stripe_provider import (
            StripeSubscriptionBillingProvider,
        )

        with override_settings(STRIPE_SECRET_KEY="sk_test_fake"):
            return StripeSubscriptionBillingProvider.__new__(
                StripeSubscriptionBillingProvider
            )

    def test_amounts_convert_to_minor_units_exactly(self):
        from integrations.subscription_billing.stripe_provider import (
            to_minor_units,
        )

        self.assertEqual(to_minor_units(Decimal("49.00")), 4900)
        self.assertEqual(to_minor_units(Decimal("4.99")), 499)
        self.assertEqual(to_minor_units(Decimal("299.00")), 29900)

    def test_the_confirmation_secret_is_read_from_the_current_shape(self):
        """Current API versions dropped latest_invoice.payment_intent.
        Reading the old path returns nothing and strands the subscription at
        'incomplete', never charged, with no error to say why."""
        adapter = self.adapter()

        ref = adapter._to_ref({
            "id": "sub_1",
            "status": "incomplete",
            "latest_invoice": {
                "confirmation_secret": {"client_secret": "pi_abc_secret"}
            },
            "items": {"data": [{"current_period_end": 1790000000}]},
        })

        self.assertEqual(ref.client_secret, "pi_abc_secret")
        self.assertEqual(ref.status, "incomplete")

    def test_the_older_payment_intent_shape_still_works(self):
        adapter = self.adapter()

        ref = adapter._to_ref({
            "id": "sub_2",
            "status": "active",
            "latest_invoice": {
                "payment_intent": {"client_secret": "pi_old_secret"}
            },
        })

        self.assertEqual(ref.client_secret, "pi_old_secret")

    def test_the_period_end_is_read_from_the_item(self):
        adapter = self.adapter()

        ref = adapter._to_ref({
            "id": "sub_3",
            "status": "active",
            "items": {"data": [{"current_period_end": 1790000000}]},
        })

        self.assertEqual(ref.current_period_end, "1790000000")

    def test_the_customer_create_carries_only_stable_parameters(self):
        """Stripe scopes an idempotency key to the parameters it was first
        used with. Sending email or name on the create means an account that
        renames itself gets IdempotencyError — a 503 it can never get past —
        and the obvious fallback of creating unkeyed silently makes the
        duplicate customer the key existed to prevent."""
        import inspect

        from integrations.subscription_billing import stripe_provider

        source = inspect.getsource(
            stripe_provider.StripeSubscriptionBillingProvider.ensure_customer
        )
        create = source.split("customers.create", 1)[1].split("options", 1)[0]

        self.assertIn("metadata", create)
        self.assertNotIn('"email"', create)
        self.assertNotIn('"name"', create)

    def test_a_bare_subscription_does_not_explode(self):
        adapter = self.adapter()

        ref = adapter._to_ref({"id": "sub_4", "status": "active"})

        self.assertEqual(ref.id, "sub_4")
        self.assertEqual(ref.client_secret, "")
        self.assertIsNone(ref.current_period_end)


class BillingWebhookTests(TestCase):
    """Stripe Billing events, signed with Stripe's own scheme."""

    def setUp(self):
        self.subscription = SubscriptionFactory(plan=plan(PlanCode.STANDARD))
        self.subscription.provider_subscription_id = "sub_hook"
        self.subscription.save(
            update_fields=["provider_subscription_id"]
        )

    def post(self, event, *, secret="whsec_test_secret"):
        import time

        import stripe

        body = json.dumps(event).encode()
        timestamp = int(time.time())
        signature = stripe.WebhookSignature._compute_signature(
            f"{timestamp}.{body.decode()}", secret
        )

        return self.client.post(
            "/webhooks/stripe/billing",
            data=body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=f"t={timestamp},v1={signature}",
        )

    def event(self, type_, obj):
        # "object": "event" is present on every real Stripe event and the SDK
        # reads it during construction, so a fixture without it is not a
        # payload Stripe would ever send.
        return {
            "id": "evt_1",
            "object": "event",
            "type": type_,
            "data": {"object": obj},
        }

    def test_an_unsigned_payload_is_refused(self):
        response = self.client.post(
            "/webhooks/stripe/billing",
            data=b"{}",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_a_wrong_secret_is_refused(self):
        response = self.post(
            self.event("invoice.paid", {"subscription": "sub_hook"}),
            secret="whsec_not_the_secret",
        )

        self.assertEqual(response.status_code, 400)

    def test_a_paid_invoice_activates(self):
        self.subscription.status = SubscriptionStatus.PAST_DUE
        self.subscription.save(update_fields=["status"])

        response = self.post(
            self.event("invoice.paid", {"subscription": "sub_hook"})
        )
        self.subscription.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.subscription.status, SubscriptionStatus.ACTIVE
        )

    def test_a_failed_charge_is_past_due_not_cancelled(self):
        """Cutting off a business the first time a card expires is the wrong
        end of the trade."""
        self.post(
            self.event(
                "invoice.payment_failed", {"subscription": "sub_hook"}
            )
        )
        self.subscription.refresh_from_db()

        self.assertEqual(
            self.subscription.status, SubscriptionStatus.PAST_DUE
        )

    def test_a_deleted_subscription_cancels(self):
        self.post(
            self.event(
                "customer.subscription.deleted", {"id": "sub_hook"}
            )
        )
        self.subscription.refresh_from_db()

        self.assertEqual(
            self.subscription.status, SubscriptionStatus.CANCELLED
        )

    def test_a_late_paid_event_cannot_resurrect_a_cancellation(self):
        """Delivery is out of order, and cancellation is a decision rather
        than an observation."""
        self.subscription.status = SubscriptionStatus.CANCELLED
        self.subscription.save(update_fields=["status"])

        self.post(
            self.event("invoice.paid", {"subscription": "sub_hook"})
        )
        self.subscription.refresh_from_db()

        self.assertEqual(
            self.subscription.status, SubscriptionStatus.CANCELLED
        )

    def test_an_unrelated_event_is_acknowledged_not_refused(self):
        """A 400 would have Stripe retry until it disables the endpoint,
        taking the events we do care about with it."""
        response = self.post(
            self.event("customer.created", {"id": "cus_x"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["handled"])

    def test_an_event_for_an_unknown_subscription_is_acknowledged(self):
        response = self.post(
            self.event("invoice.paid", {"subscription": "sub_unknown"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["handled"])

    def test_delivery_twice_is_harmless(self):
        event = self.event("invoice.paid", {"subscription": "sub_hook"})

        self.post(event)
        second = self.post(event)
        self.subscription.refresh_from_db()

        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            self.subscription.status, SubscriptionStatus.ACTIVE
        )


class SetupIntentEndpointTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_it_says_so_when_nothing_collects_money(self):
        """Better than a card form that can never work."""
        SubscriptionService().subscribe(
            account=self.user, plan_code=PlanCode.FOUNDING
        )

        response = self.client.post(
            "/api/v1/billing/payment-method/setup", {}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["data"]["collects_money"])
        self.assertEqual(response.data["data"]["client_secret"], "")

    def test_a_plan_is_required_first(self):
        response = self.client.post(
            "/api/v1/billing/payment-method/setup", {}, format="json"
        )

        self.assertEqual(response.status_code, 200)


class CardOnFileTests(TestCase):
    """BILLING-1: read and replace the card; a new card settles a past-due
    balance straight away."""

    def setUp(self):
        self.stub = CollectingStub()
        self.subscription = SubscriptionFactory(plan=plan(PlanCode.FOUNDING))
        self.service = BillingProviderService(provider=self.stub)
        self.service.start(self.subscription)

    def test_no_card_reads_as_none(self):
        self.assertIsNone(self.service.card(self.subscription))

    def test_replacing_sets_it_on_the_subscription_too(self):
        card = self.service.replace_card(self.subscription, "pm_new")

        self.assertEqual(card.last4, "4242")
        call = dict(self.stub.calls)["set_default_card"]
        self.assertEqual(call["subscription_id"], "sub_stub")

    def test_a_past_due_subscription_recovers_with_the_new_card(self):
        self.subscription.status = SubscriptionStatus.PAST_DUE
        self.subscription.save(update_fields=["status"])

        self.service.replace_card(self.subscription, "pm_new")

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, SubscriptionStatus.ACTIVE)

    def test_a_declined_card_is_a_field_error(self):
        from rest_framework.exceptions import ValidationError

        self.stub.fail_with = CardDeclined("Your card was declined.")

        with self.assertRaises(ValidationError) as caught:
            self.service.replace_card(self.subscription, "pm_bad")

        self.assertIn("payment_method_id", caught.exception.detail)


class CardEndpointMockTests(TestCase):
    """On the mock deployment nothing collects money: no card to show."""

    def test_get_is_null_and_post_is_refused(self):
        from apps.billing.services.subscription_service import (
            SubscriptionService,
        )
        from rest_framework.test import APIClient

        from apps.vendors.factories import UserFactory

        user = UserFactory()
        SubscriptionService().subscribe(account=user, plan_code=PlanCode.STANDARD)
        client = APIClient()
        client.force_authenticate(user=user)

        self.assertIsNone(
            client.get("/api/v1/billing/payment-method").json()["data"]
        )
        response = client.post(
            "/api/v1/billing/payment-method",
            {"payment_method_id": "pm_x"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
