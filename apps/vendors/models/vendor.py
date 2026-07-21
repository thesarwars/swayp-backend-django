from django.db import models
from django.contrib.auth.models import User
from apps.common.models import BaseModel
# Create your models here.


class Vendor(BaseModel):
    class PaymentMethod(models.TextChoices):
        STRIPE = 'STRIPE', 'Stripe Bill Pay Network'
        ACH = 'ACH', 'ACH Bank Transfer'
        CHECK = 'CHECK', 'Physical Check'

    class ChoiceVendorMethod(models.TextChoices):
        STRIPE_SEARCH = 'STRIPE_SEARCH', 'Search Stripe Directory'
        QR_CODE = 'QR_CODE', 'Scan Vendor QR Code'
        MANUAL = 'MANUAL', 'Enter Manually'

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='vendors')
    # basic vendor information
    name = models.CharField(max_length=255)
    business_type = models.CharField(max_length=100)
    delivery_speed = models.CharField(max_length=100,blank=True, null=True)
    
    # payment and dashboard overview fields
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.STRIPE)
    choicevendor_method = models.CharField(max_length=20, choices=ChoiceVendorMethod.choices, default=ChoiceVendorMethod.MANUAL)

    # if vendor is added via Stripe
    stripe_vendor_id = models.CharField(max_length=255, blank=True, null=True)
    account_number_ref = models.CharField(max_length=100, blank=True, null=True)
    is_verified = models.BooleanField(default=False)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    def __str__(self):
        return f"{self.name} ({self.payment_method})"


class VendorBankDetail(BaseModel):
    class AccountType(models.TextChoices):
        CHECKING = 'CHECKING', 'Checking'
        SAVINGS = 'SAVINGS', 'Savings'

    vendor = models.OneToOneField(Vendor, on_delete=models.CASCADE, related_name='bank_details')
    
    routing_number = models.CharField(max_length=50)
    account_number = models.CharField(max_length=50)
    account_type = models.CharField(max_length=20, choices=AccountType.choices, default=AccountType.CHECKING)
    account_holder_name = models.CharField(max_length=255)

    def __str__(self):
        return f"Bank for {self.vendor.name}"