"""factory_boy factories for the bill domain (E4-S1)."""

import datetime as dt

import factory
from django.utils import timezone

from apps.bills.models.bill import Bill
from apps.bills.models.bill_occurrence import BillOccurrence
from apps.bills.models.standing_authorization import StandingAuthorization
from apps.common.enums import (
    AutopayMode,
    BillFrequency,
    BillOccurrenceStatus,
    BillSource,
    BillType,
)
from apps.vendors.factories import (
    BillCategoryFactory,
    UserFactory,
    VendorFactory,
)


class BillFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Bill

    user = factory.SubFactory(UserFactory)
    vendor = factory.SubFactory(
        VendorFactory, user=factory.SelfAttribute("..user")
    )
    category = factory.SubFactory(BillCategoryFactory)
    bill_type = BillType.FIXED
    amount = "3200.00"
    frequency = BillFrequency.MONTHLY
    # Fixed rather than relative to today, so schedule assertions are stable.
    anchor_date = dt.date(2026, 8, 1)
    autopay_mode = AutopayMode.REMIND
    source = BillSource.MANUAL


class BillOccurrenceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BillOccurrence

    bill = factory.SubFactory(BillFactory)
    due_date = dt.date(2026, 8, 1)
    amount = "3200.00"
    status = BillOccurrenceStatus.UPCOMING


class StandingAuthorizationFactory(factory.django.DjangoModelFactory):
    """A live autopay mandate. Set revoked_at to model a revoked one."""

    class Meta:
        model = StandingAuthorization

    bill = factory.SubFactory(BillFactory, autopay_mode=AutopayMode.AUTO)
    authorization_text = (
        "I authorize Swayp to debit my account for this recurring bill "
        "until I revoke this authorization."
    )
    accepted_at = factory.LazyFunction(timezone.now)
    ip = "203.0.113.9"
    user_agent = "SwaypApp/1.0 (factory)"
