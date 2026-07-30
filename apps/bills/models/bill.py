from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.common.enums import (
    AutopayMode,
    BillFrequency,
    BillSource,
    BillType,
)
from apps.common.models import BaseModel
from apps.bill_categories.models import BillCategory
from apps.vendors.models import Vendor, VendorPaymentMethod


class Bill(BaseModel):
    """
    A recurring billing rule.

    A Bill never represents an individual payment.
    Each billing cycle is represented by BillOccurrence.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="bills")
    # Multi-entity scoping (E10-S3); null on single-entity accounts.
    entity = models.ForeignKey(
        "teams.Entity",
        on_delete=models.PROTECT,
        related_name="bills",
        null=True,
        blank=True,
    )
    vendor = models.ForeignKey(Vendor,on_delete=models.PROTECT,related_name="bills")
    bill_type = models.CharField(max_length=10,choices=BillType.choices,default=BillType.FIXED)
    amount = models.DecimalField(max_digits=18,decimal_places=2)
    category = models.ForeignKey(BillCategory,on_delete=models.PROTECT,related_name="bills")
    notes = models.TextField(blank=True,default="")
    frequency = models.CharField(max_length=20,choices=BillFrequency.choices)
    anchor_date = models.DateField()
    autopay_mode = models.CharField(max_length=10,choices=AutopayMode.choices,default=AutopayMode.REMIND)
    payment_method = models.ForeignKey(VendorPaymentMethod,on_delete=models.SET_NULL,related_name="bills",null=True,blank=True)
    source = models.CharField(max_length=20,choices=BillSource.choices,default=BillSource.MANUAL)

    # Soft delete (E4-S5). Bill -> BillOccurrence is CASCADE, so a real delete
    # would take settled occurrences with it and the AC requires paid history
    # to survive. Deleting drops future unpaid occurrences and stamps this
    # instead; every selector filters on it.
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bills"
        ordering = ["-created_at"]

        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["vendor"]),
            models.Index(fields=["category"]),
            models.Index(fields=["deleted_at"]),
        ]

        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="bill_amount_positive",
            )
        ]

    def clean(self):
        super().clean()

        if self.vendor and self.vendor.user_id != self.user_id:
            raise ValidationError(
                {
                    "vendor": "Vendor does not belong to this user."
                }
            )

        if (
            self.vendor
            and self.payment_method
            and self.payment_method.vendor_id != self.vendor_id
        ):
            raise ValidationError(
                {
                    "payment_method": (
                        "Selected payment method does not belong to this vendor."
                    )
                }
            )

    def __str__(self):
        return (
            f"{self.vendor.name} "
            f"({self.get_frequency_display()})"
        )
