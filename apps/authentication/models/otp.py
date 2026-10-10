from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class OTPPurpose(models.TextChoices):
    REGISTRATION = "REGISTRATION", "Registration"
    LOGIN = "LOGIN", "Login"
    RESET_PASSWORD = "RESET_PASSWORD", "Reset Password"
    # Adding or changing the phone number from settings (AUTH-10). The code
    # is bound to the number it was issued for — see OTP.target.
    PHONE_CHANGE = "PHONE_CHANGE", "Phone Change"


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

    # The value the code authorises, for purposes that change something
    # (PHONE_CHANGE: the new number). Without it a code requested for one
    # number could be spent setting another. Blank for every other purpose.
    target = models.CharField(
        max_length=32,
        blank=True,
        default="",
    )

    @property
    def is_exhausted(self):
        """True once the code has taken OTP_MAX_ATTEMPTS wrong guesses.

        An exhausted code is refused even when the guess is right: the cap is
        only a cap if the next correct guess cannot still get through.
        """
        return self.attempts >= getattr(settings, "OTP_MAX_ATTEMPTS", 5)

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