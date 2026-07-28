from django.db import models

from apps.common.models import BaseModel


class OTPPurpose(models.TextChoices):
    REGISTRATION = "REGISTRATION", "Registration"
    LOGIN = "LOGIN", "Login"
    RESET_PASSWORD = "RESET_PASSWORD", "Reset Password"


class OTPChannel(models.TextChoices):
    # Reserved. The SMS OTP screens are designed, but SMS delivery is deferred
    # this release (BRD §1.2) — requesting it is rejected, never a silent no-op.
    SMS = "SMS", "SMS"
    EMAIL = "EMAIL", "Email"


class OTP(BaseModel):

    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="otps",
    )

    code_hash = models.CharField(
        max_length=255,
    )

    purpose = models.CharField(
        max_length=30,
        choices=OTPPurpose.choices,
    )

    expires_at = models.DateTimeField()

    used_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    attempts = models.PositiveSmallIntegerField(
        default=0,
    )

    channel = models.CharField(
        max_length=10,
        choices=OTPChannel.choices,
        default=OTPChannel.EMAIL,
    )

    class Meta:
        db_table = "otps"

        indexes = [
            models.Index(
                fields=[
                    "user",
                    "purpose",
                ]
            ),
            models.Index(
                fields=[
                    "expires_at",
                ]
            ),
        ]