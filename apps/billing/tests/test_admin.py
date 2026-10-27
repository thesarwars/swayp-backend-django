"""The billing tables are in the admin, and every page renders."""

from django.contrib import admin
from django.test import TestCase
from django.urls import reverse

from apps.billing.factories import (
    EnterpriseAddOnFactory,
    FeeChargeFactory,
    SubscriptionFactory,
)
from apps.billing.models import (
    AllowanceCounter,
    EnterpriseAddOn,
    FeeCharge,
    Plan,
    Subscription,
)
from apps.users.models.user import User


class BillingAdminTests(TestCase):

    def setUp(self):
        self.staff = User.objects.create_superuser(
            email="root@acme.com", password="Str0ng!Passphrase1"
        )
        self.client.force_login(self.staff)
        subscription = SubscriptionFactory()
        EnterpriseAddOnFactory(subscription=subscription)
        FeeChargeFactory(subscription=subscription)
        AllowanceCounter.objects.create(
            subscription=subscription, kind="CHECKS",
            period_start=subscription.period_start,
        )

    def test_every_billing_model_is_registered(self):
        for model in (Plan, Subscription, EnterpriseAddOn, FeeCharge,
                      AllowanceCounter):
            with self.subTest(model=model.__name__):
                self.assertIn(model, admin.site._registry)

    def test_every_page_renders(self):
        for model in (Plan, Subscription, EnterpriseAddOn, FeeCharge,
                      AllowanceCounter):
            obj = model.objects.first()
            meta = model._meta

            for view, args in (("changelist", []), ("change", [obj.pk]),
                               ("add", [])):
                url = reverse(
                    f"admin:{meta.app_label}_{meta.model_name}_{view}",
                    args=args,
                )

                with self.subTest(model=meta.model_name, view=view):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_a_plan_price_can_be_edited(self):
        plan = Plan.objects.get(code="STANDARD")
        url = reverse("admin:billing_plan_change", args=[plan.pk])
        form = self.client.get(url).context["adminform"].form
        data = {k: v for k, v in form.initial.items() if v is not None}
        data.update({"monthly_price": "109.00", "is_active": "on"})

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 302, getattr(
            response, "context", {}) and response.context["adminform"].errors)
        plan.refresh_from_db()
        self.assertEqual(str(plan.monthly_price), "109.00")
