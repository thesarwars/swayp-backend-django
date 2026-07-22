from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from apps.common.models import BaseModel
from .constants import (
    VendorPaymentMethodType,
    BankAccountType,
)
from .vendor import Vendor


class VendorPaymentMethod(BaseModel):

    vendor = models.ForeignKey(Vendor,on_delete=models.CASCADE,related_name="payment_methods")
    method_type = models.CharField(max_length=10,choices=VendorPaymentMethodType.choices)
    is_primary = models.BooleanField(default=False)

    # -------------------
    # NETWORK
    # -------------------

    network_payee_ref = models.CharField(max_length=100,blank=True)
    supports_same_day = models.BooleanField(default=False)

    # -------------------
    # ACH
    # -------------------

    provider = models.CharField(max_length=20,blank=True)
    provider_token = models.CharField(max_length=100,blank=True)
    account_last4 = models.CharField(max_length=4,blank=True)
    account_type = models.CharField(max_length=20,choices=BankAccountType.choices,blank=True)
    account_holder_name = models.CharField(max_length=150,blank=True)
    aba_bank_name = models.CharField(max_length=100,blank=True)
    payee_verified = models.BooleanField(default=False)

    # -------------------
    # CHECK
    # -------------------

    check_legal_name = models.CharField(max_length=150,blank=True)
    street = models.CharField(max_length=255,blank=True)
    line2 = models.CharField(max_length=255,blank=True)
    city = models.CharField(max_length=100,blank=True)
    state = models.CharField(max_length=2,blank=True)
    zip_code = models.CharField(max_length=10,blank=True)
    check_memo = models.CharField(max_length=100,blank=True)

    class Meta:
        db_table = "vendor_payment_methods"

        constraints = [
            models.UniqueConstraint(
                fields=["vendor"],
                condition=Q(is_primary=True),
                name="one_primary_method_per_vendor"
            )
        ]

    def clean(self):
        """
        Validate required fields based on payment method.
        """

        if self.method_type == VendorPaymentMethodType.NETWORK:
            if not self.network_payee_ref:
                raise ValidationError(
                    "Network payee reference is required."
                )

        elif self.method_type == VendorPaymentMethodType.ACH:

            required = [
                self.provider,
                self.provider_token,
                self.account_last4,
                self.account_holder_name,
            ]

            if not all(required):
                raise ValidationError(
                    "ACH payment information is incomplete."
                )

        elif self.method_type == VendorPaymentMethodType.CHECK:

            required = [
                self.check_legal_name,
                self.street,
                self.city,
                self.state,
                self.zip_code,
            ]

            if not all(required):
                raise ValidationError(
                    "Check mailing information is incomplete."
                )

    def __str__(self):
        return f"{self.vendor.name} - {self.method_type}"