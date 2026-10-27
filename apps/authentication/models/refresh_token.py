from django.db import models

from apps.common.models import BaseModel


class RefreshToken(BaseModel):
    """One signed-in device: a session.

    The row's id travels in every token the session mints, as the ``sid``
    claim, and survives refresh rotation, so one device is one row however
    often it refreshes. That is what lets the user list where they are signed
    in and end one, and what lets an access token be refused the moment its
    session ends rather than when it expires.
    """

    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="refresh_tokens",
    )

    token_hash = models.CharField(
        max_length=255,
    )

    user_agent = models.TextField()

    # Null when no client address could be read; a made-up one would be
    # worse than none on the screen a user checks for intruders.
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    expires_at = models.DateTimeField()

    # Refreshed on token refresh and, at most every few minutes, on use.
    last_used_at = models.DateTimeField(null=True, blank=True)

    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "refresh_tokens"
        indexes = [
            models.Index(fields=["user", "revoked_at"]),
        ]
