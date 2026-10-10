from django.conf import settings
from django.db import models
from apps.common.models import BaseModel
from apps.bill_categories.models.bill_category import BillCategory
from apps.users.models.user import User

from apps.common.enums import VendorSource, VendorStatus


class Vendor(BaseModel):
    """
    User owned payee.

    One Provider can be saved by many users as Vendor.
    """

    user = models.ForeignKey(User,on_delete=models.CASCADE,related_name="vendors")

    # Multi-entity scoping (E10-S3). Nullable and PROTECT: a single-entity
    # account leaves it null and is unaffected, and an entity is archived
    # rather than deleted precisely so this never dangles.
    entity = models.ForeignKey(
        "teams.Entity",
        on_delete=models.PROTECT,
        related_name="vendors",
        null=True,
        blank=True,
    )

    name = models.CharField(
        max_length=150
    )

    category = models.ForeignKey(BillCategory,on_delete=models.PROTECT,related_name="vendors")
    logo = models.URLField(max_length=500,blank=True)

    business_type = models.CharField(
        max_length=100,
        blank=True
    )

    notes = models.TextField(
        blank=True
    )

    source = models.CharField(
        max_length=20,
        choices=VendorSource.choices,
        default=VendorSource.MANUAL
    )

    status = models.CharField(
        max_length=20,
        choices=VendorStatus.choices,
        default=VendorStatus.ACTIVE
    )

    directory_payee_id = models.CharField(
        max_length=100,
        blank=True
    )

    directory_verified = models.BooleanField(
        default=False
    )

    late_fee_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True
    )

    late_fee_grace_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True
    )

    # When the vendor was deleted (VEND-11). Its bills are soft-deleted with
    # this same timestamp, which is how restore tells them apart from bills
    # the user had deleted on their own before.
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "vendors"

        ordering = [
            "name"
        ]

        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["status"]),
            models.Index(fields=["category"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return self.name