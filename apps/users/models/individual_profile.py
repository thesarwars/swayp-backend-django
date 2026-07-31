from django.db import models

from apps.common.models import BaseModel


class IndividualProfile(BaseModel):

    profile = models.OneToOneField(
        "users.Profile",
        on_delete=models.CASCADE,
        related_name="individual",
    )

    billing_address = models.TextField(blank=True, default="")

    class Meta:
        db_table = "individual_profiles"