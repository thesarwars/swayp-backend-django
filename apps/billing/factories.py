"""factory_boy factories for billing (E9)."""

import datetime as dt

import factory

from apps.billing.models import (
    ADDON_PRICES,
    FEE_AMOUNTS,
    AddOnKind,
    AllowanceCounter,
    AllowanceKind,
    EnterpriseAddOn,
    FeeCharge,
    FeeKind,
    Plan,
    PlanCode,
    Subscription,
    SubscriptionStatus,
)
from apps.vendors.factories import UserFactory


class PlanFactory(factory.django.DjangoModelFactory):
    """Defaults to Founding. The seed migration already creates the real
    three, so tests normally look those up rather than build new ones."""

    class Meta:
        model = Plan
        django_get_or_create = ("code",)

    code = PlanCode.FOUNDING
    name = "Founding"
    monthly_price = "49.00"
    seat_limit = 3
    bank_limit = 1
    free_checks_per_month = 2
    included_entities = 1
    price_locked = True


class SubscriptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Subscription

    account = factory.SubFactory(UserFactory)
    plan = factory.SubFactory(PlanFactory)
    status = SubscriptionStatus.ACTIVE
    # Fixed dates so cycle assertions stay stable.
    period_start = dt.date(2026, 8, 1)
    period_end = dt.date(2026, 9, 1)


class AllowanceCounterFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AllowanceCounter

    subscription = factory.SubFactory(SubscriptionFactory)
    kind = AllowanceKind.CHECKS
    period_start = factory.SelfAttribute("subscription.period_start")
    used = 0


class FeeChargeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FeeCharge

    subscription = factory.SubFactory(SubscriptionFactory)
    payment = factory.SubFactory("apps.payments.factories.PaymentFactory")
    kind = FeeKind.SAME_DAY_ACH
    amount = factory.LazyAttribute(
        lambda o: FEE_AMOUNTS.get(o.kind, "0.00")
    )


class EnterpriseAddOnFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EnterpriseAddOn

    subscription = factory.SubFactory(SubscriptionFactory)
    kind = AddOnKind.ERP_SYNC
    quantity = 1
    unit_price = factory.LazyAttribute(
        lambda o: ADDON_PRICES.get(o.kind, "0.00")
    )
