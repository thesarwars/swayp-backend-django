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

    # Optional because the Create Account screen does not ask for it —
    # onboarding Step 1 and Settings do. Blank, never null, so callers never
    # have to test for both.
    billing_address = models.TextField(blank=True, default="")

    # Collected on the Create Account screen (industry, business size) and on
    # onboarding Step 1 (the rest). Free text rather than choices: the design
    # shows dropdowns but the option lists are not specified anywhere, and
    # inventing an enum would reject whatever the real list turns out to be.
    industry = models.CharField(max_length=100, blank=True, default="")
    business_size = models.CharField(max_length=50, blank=True, default="")
    trading_name = models.CharField(max_length=255, blank=True, default="")
    business_type = models.CharField(max_length=100, blank=True, default="")
    website = models.URLField(max_length=255, blank=True, default="")
    # Distinct from Entity.ein (E10 multi-entity): this is the registering
    # business's own number, captured before any entity exists.
    ein = models.CharField(max_length=20, blank=True, default="")

    class Meta:
        db_table = "business_profiles"