import uuid

from django.db import models

from apps.bill_categories.models import BillCategory
from apps.common.models import BaseModel

class Provider(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    

    category = models.ForeignKey(
        BillCategory,
        on_delete=models.PROTECT,
        related_name="providers",
    )

    provider_name = models.CharField(max_length=150)
    provider_code = models.CharField(max_length=50, unique=True)

    logo = models.URLField(max_length=500)

    description = models.TextField(blank=True)

    country = models.CharField(max_length=50)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    supports_auto_pay = models.BooleanField(default=False)

    

    class Meta:
        db_table = "providers"
        ordering = ["provider_name"]
        indexes = [
            models.Index(fields=["category"]),
            models.Index(fields=["status"]),
            models.Index(fields=["provider_name"]),
            models.Index(fields=["provider_code"]),
            models.Index(fields=["country"]),
        ]

    def __str__(self):
        return self.provider_name