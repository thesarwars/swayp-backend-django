"""The billing webhook keeps Swayp's plan and period in step with Stripe.

Delivery is at least once and out of order: a repeated event is skipped by
its id, and an older subscription update cannot overwrite a newer one.
"""

from django.test import TestCase, override_settings

from apps.billing.factories import SubscriptionFactory
from apps.billing.models import BillingWebhookEvent, Plan, PlanCode
from apps.billing.tests.test_stripe_billing import BillingWebhookTests

T0 = 1_790_000_000  # 2026-09-21 UTC
DAY = 86_400


def utc_day(ts):
    import datetime as dt

    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date()


@override_settings(STRIPE_BILLING_WEBHOOK_SECRET="whsec_test_secret")
class WebhookSyncTests(TestCase):

    post = BillingWebhookTests.post

    def setUp(self):
        Plan.objects.filter(code=PlanCode.STANDARD).update(provider_price_id="price_std")
        Plan.objects.filter(code=PlanCode.ENTERPRISE).update(provider_price_id="price_ent")
        self.subscription = SubscriptionFactory(
            plan=Plan.objects.get(code=PlanCode.STANDARD)
        )
        self.subscription.provider_subscription_id = "sub_sync"
        self.subscription.save(update_fields=["provider_subscription_id"])

    def updated(self, *, event_id, created, price="price_ent", **extra):
        obj = {
            "id": "sub_sync",
            "status": "active",
            "items": {
                "data": [
                    {
                        "price": {"id": price},
                        "current_period_start": T0,
                        "current_period_end": T0 + 30 * DAY,
                    }
                ]
            },
            **extra,
        }

        return self.post(
            {
                "id": event_id,
                "object": "event",
                "type": "customer.subscription.updated",
                "created": created,
                "data": {"object": obj},
            }
        )

    def test_the_plan_and_period_follow_stripe(self):
        response = self.updated(event_id="evt_a", created=T0)

        self.subscription.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.subscription.plan.code, PlanCode.ENTERPRISE)
        self.assertEqual(self.subscription.period_start, utc_day(T0))
        self.assertEqual(self.subscription.period_end, utc_day(T0 + 30 * DAY))

    def test_an_unknown_price_leaves_the_plan(self):
        self.updated(event_id="evt_a", created=T0, price="price_somebody_else")

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan.code, PlanCode.STANDARD)

    def test_a_cancel_made_in_stripe_shows_in_swayp(self):
        self.updated(event_id="evt_a", created=T0, cancel_at_period_end=True)

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.cancels_on, utc_day(T0 + 30 * DAY))

        self.updated(event_id="evt_b", created=T0 + 1, cancel_at_period_end=False)

        self.subscription.refresh_from_db()
        self.assertIsNone(self.subscription.cancels_on)

    def test_an_older_event_cannot_overwrite_a_newer_one(self):
        self.updated(event_id="evt_new", created=T0 + 100, price="price_ent")
        self.updated(event_id="evt_old", created=T0, price="price_std")

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan.code, PlanCode.ENTERPRISE)

    def test_a_repeated_event_is_applied_once(self):
        self.updated(event_id="evt_same", created=T0)
        response = self.updated(event_id="evt_same", created=T0)

        self.assertTrue(response.json()["duplicate"])
        self.assertEqual(BillingWebhookEvent.objects.filter(event_id="evt_same").count(), 1)
