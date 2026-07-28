"""factory_boy factories for the banking domain (E5-S1).

Kept here rather than in a shared package so each app owns its own fixtures.
Everything is deterministic where the value matters — a scan fixture with a
random detected_count would make assertions meaningless.
"""

import factory
from django.utils import timezone

from apps.banking.models import (
    BankAccount,
    BankConnection,
    BankConnectionStatus,
    BillDetectionCandidate,
    TransactionScan,
)
from apps.common.enums import BankAccountType, BillFrequency, ScanStatus
from apps.users.models import User


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.com")

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        if create:
            self.set_password(extracted or "Sw@yp-Factory-1")
            self.save(update_fields=["password"])


class BankConnectionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BankConnection

    user = factory.SubFactory(UserFactory)
    provider = "MOCK"
    item_id = factory.Sequence(lambda n: f"mock-item-{n}")
    # Encrypted at rest by the field itself.
    access_token = "mock-access-token"
    institution_name = "Chase Bank"
    status = BankConnectionStatus.ACTIVE
    consented_at = factory.LazyFunction(timezone.now)


class BankAccountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BankAccount

    connection = factory.SubFactory(BankConnectionFactory)
    external_id = factory.Sequence(lambda n: f"mock-acc-{n}")
    name = "Chase Business Checking"
    mask = "4821"
    account_type = BankAccountType.CHECKING
    is_default_funding_source = True


class TransactionScanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TransactionScan

    connection = factory.SubFactory(BankConnectionFactory)
    status = ScanStatus.DONE
    months_history = 12
    transactions_scanned = 46
    detected_count = 0


class BillDetectionCandidateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BillDetectionCandidate

    scan = factory.SubFactory(TransactionScanFactory)
    vendor_name = factory.Sequence(lambda n: f"Vendor {n}")
    cadence = BillFrequency.MONTHLY
    due_day = 15
    amount = "389.00"
    occurrences = 12
    selected = True
