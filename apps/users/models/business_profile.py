from django.db import models

from apps.common.models import BaseModel


class BusinessProfile(BaseModel):

    profile = models.OneToOneField(
        "users.Profile",
        on_delete=models.CASCADE,
        related_name="business",
    )

    business_name = models.CharField(
        max_length=255,
    )

    poc_name = models.CharField(
        max_length=255,
    )

    billing_address = models.TextField()

    class Meta:
        db_table = "business_profiles"