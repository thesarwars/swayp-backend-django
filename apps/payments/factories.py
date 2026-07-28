"""factory_boy factories for the payments domain (E6-S1)."""

import factory
from django.utils import timezone

from apps.common.enums import PaymentProcessor, PaymentRail, PaymentStatus
from apps.payments.models import (
    Payment,
    PaymentAuthorization,
    PaymentBatch,
    PaymentStage,
    PaymentStageName,
    WebhookEvent,
)
from apps.vendors.factories import UserFactory, VendorFactory


class PaymentBatchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PaymentBatch

    user = factory.SubFactory(UserFactory)
    total = "3200.00"
    count = 1


class PaymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Payment

    user = factory.SubFactory(UserFactory)
    vendor = factory.SubFactory(
        VendorFactory, user=factory.SelfAttribute("..user")
    )
    amount = "3200.00"
    total = "3200.00"
    rail = PaymentRail.ACH_STANDARD
    processor = PaymentProcessor.MOCK
    status = PaymentStatus.PENDING
    payment_method = "ACH"
    transaction_reference = factory.Sequence(
        lambda n: f"SWP-20260801-{n:04d}"
    )


class PaymentStageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PaymentStage

    payment = factory.SubFactory(PaymentFactory)
    stage = PaymentStageName.AUTHORIZED
    order = 1


class PaymentAuthorizationFactory(factory.django.DjangoModelFactory):
    """Consent for a single payment. Pass batch=… for the batch variant."""

    class Meta:
        model = PaymentAuthorization

    payment = factory.SubFactory(PaymentFactory)
    batch = None
    authorization_text = (
        "I authorize Swayp to debit my account for this payment."
    )
    accepted_at = factory.LazyFunction(timezone.now)
    ip = "203.0.113.9"
    user_agent = "SwaypApp/1.0 (factory)"


class WebhookEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WebhookEvent

    processor = "MOCK"
    event_id = factory.Sequence(lambda n: f"evt_{n}")
    event_type = "transfer.completed"
    payload = factory.LazyFunction(dict)
