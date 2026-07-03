from django.db import models

from apps.common.models import BaseModel


class OTPPurpose(models.TextChoices):
    REGISTRATION = "REGISTRATION", "Registration"
    LOGIN = "LOGIN", "Login"
    RESET_PASSWORD = "RESET_PASSWORD", "Reset Password"


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