"""A device a user can be reached on (E8-S5).

The push equivalent of an email address, with one difference that shapes the
whole model: **the token identifies the device, not the person.**

That is why ``token`` is unique across the table rather than unique per user.
A shared tablet, or a phone where one person signs out and another signs in,
produces the same FCM token under a second account — and if both rows were
allowed to exist, the first user's bill reminders would keep arriving on a
device that now belongs to someone else. Registration therefore *reassigns*
an existing token rather than creating a second row, which makes signing in
the act that moves the device.

Rows are deactivated, never deleted, when FCM reports a token dead. A user who
reinstalls gets the same row reactivated instead of accumulating a new one per
install, and the timestamps stay available for "why did this person stop
getting notifications".
"""

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class DevicePlatform(models.TextChoices):
    IOS = "IOS", "iOS"
    ANDROID = "ANDROID", "Android"
    WEB = "WEB", "Web"


class DeviceToken(BaseModel):

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="device_tokens",
    )

    #: The FCM registration token. Unique table-wide — see the module docstring.
    token = models.CharField(max_length=512, unique=True)

    platform = models.CharField(
        max_length=10,
        choices=DevicePlatform.choices,
    )

    #: Free text from the client ("iPhone 15", "Chrome on Windows"), shown in
    #: a future "your devices" screen. Never used to route a message.
    device_name = models.CharField(max_length=120, blank=True, default="")

    #: False once the provider reports the token permanently undeliverable.
    #: Sends filter on this, so a dead device costs one boolean rather than a
    #: failed network call on every notification for the rest of time.
    is_active = models.BooleanField(default=True)

    #: Refreshed on every registration. FCM tokens rotate, and a client that
    #: has stopped re-registering is the signal that a row is stale.
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            # The send path's only query: active tokens for one user.
            models.Index(fields=["user", "is_active"]),
        ]
        ordering = ["-last_seen_at"]

    def __str__(self):
        return f"{self.platform} device for {self.user_id}"
