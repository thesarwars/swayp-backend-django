"""Second factor: an authenticator app, and recovery codes for losing it."""

from django.conf import settings
from django.db import models

from apps.common.crypto import EncryptedTextField
from apps.common.models import BaseModel


class MFADevice(BaseModel):
    """A user's authenticator app.

    Created by setup and only in force once confirmed with a code from the
    app, so a half-finished setup can never lock anyone out. One per user:
    setting up again replaces an unconfirmed one.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mfa_device",
    )

    # The shared TOTP secret. Encrypted at rest: anyone holding it can make
    # codes, so it is a credential.
    secret = EncryptedTextField()

    confirmed_at = models.DateTimeField(null=True, blank=True)

    # The time step of the last accepted code, so a code works once even
    # within its 30 seconds.
    last_used_step = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "mfa_devices"

    def __str__(self):
        state = "on" if self.confirmed_at else "pending"

        return f"{self.user_id} MFA ({state})"

    @property
    def is_enabled(self):
        return self.confirmed_at is not None


class MFARecoveryCode(BaseModel):
    """A single-use code for signing in without the authenticator app.

    Stored as a SHA-256 digest. The codes carry 50 random bits each, so a
    slow password hash buys nothing, and checking ten Argon2 hashes on every
    attempt would cost seconds.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mfa_recovery_codes",
    )

    code_hash = models.CharField(max_length=64)

    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mfa_recovery_codes"
        indexes = [models.Index(fields=["user", "used_at"])]

    def __str__(self):
        return f"{self.user_id} recovery code"
