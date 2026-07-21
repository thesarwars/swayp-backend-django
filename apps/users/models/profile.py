from django.db import models

from apps.common.models import BaseModel


class AccountType(models.TextChoices):
    INDIVIDUAL = "INDIVIDUAL", "Individual"
    BUSINESS = "BUSINESS", "Business"


class Profile(BaseModel):

    user = models.OneToOneField(
        "users.User",
        on_delete=models.CASCADE,
        related_name="profile",
    )

    account_type = models.CharField(
        max_length=20,
        choices=AccountType.choices,
    )

    full_name = models.CharField(
        max_length=255,
    )

    address = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "profiles"