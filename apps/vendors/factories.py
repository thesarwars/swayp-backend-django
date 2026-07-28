"""factory_boy factories for the vendor domain (E3-S1).

The payment-method factory has one trait per branch, because a NETWORK method
and a CHECK method require entirely different fields — a single factory with
everything filled in would never resemble a real row.
"""

import factory

from apps.bill_categories.models import BillCategory
from apps.common.enums import (
    BankAccountType,
    VendorPaymentMethodType,
    VendorSource,
    VendorStatus,
)
from apps.users.models import User
from apps.vendors.models import Vendor, VendorPaymentMethod


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"vendor-user{n}@example.com")

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        if create:
            self.set_password(extracted or "Sw@yp-Factory-1")
            self.save(update_fields=["password"])


class BillCategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BillCategory
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Category {n}")
    icon = "https://cdn.swayp.com/icons/default.png"
    color = "#4F46E5"
    display_order = factory.Sequence(lambda n: n)


class VendorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Vendor

    user = factory.SubFactory(UserFactory)
    category = factory.SubFactory(BillCategoryFactory)
    name = factory.Sequence(lambda n: f"Vendor {n}")
    source = VendorSource.MANUAL
    status = VendorStatus.ACTIVE


class VendorPaymentMethodFactory(factory.django.DjangoModelFactory):
    """Defaults to ACH. Use the traits for the other two branches."""

    class Meta:
        model = VendorPaymentMethod

    class Params:
        network = factory.Trait(
            method_type=VendorPaymentMethodType.NETWORK,
            network_payee_ref=factory.Sequence(lambda n: f"payee_{n}"),
            provider="",
            provider_token="",
            account_last4="",
            account_holder_name="",
        )
        check = factory.Trait(
            method_type=VendorPaymentMethodType.CHECK,
            check_legal_name="WeWork Inc",
            street="115 W 18th St",
            city="New York",
            state="NY",
            zip_code="10011",
            provider="",
            provider_token="",
            account_last4="",
            account_holder_name="",
        )

    vendor = factory.SubFactory(VendorFactory)
    method_type = VendorPaymentMethodType.ACH
    is_primary = True

    # Tokenized values only — a raw account number never reaches a model.
    provider = "MOOV"
    provider_token = factory.Sequence(lambda n: f"pm_moov_{n}")
    account_last4 = "8837"
    account_type = BankAccountType.CHECKING
    account_holder_name = "WeWork Inc"
    aba_bank_name = "Chase Bank"
