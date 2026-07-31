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

    # The Create Account screen's two required checkboxes. Stored with a
    # timestamp because they are legal artifacts: "did this account accept
    # the terms, and when" has to be answerable later, and a boolean alone
    # cannot answer the second half.
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    signatory_confirmed_at = models.DateTimeField(null=True, blank=True)
    # The third checkbox is a preference, not a consent record.
    marketing_opt_in = models.BooleanField(default=False)

    # The one part of onboarding progress that cannot be derived. Every other
    # step is read from what it creates — a business name, a subscription, a
    # bank connection — but "Skip for now" on the bank step leaves no trace,
    # and without this the wizard would keep returning someone to a step they
    # deliberately declined.
    onboarding_bank_skipped = models.BooleanField(default=False)

    class Meta:
        db_table = "profiles"