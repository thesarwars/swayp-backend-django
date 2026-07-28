"""OTP issuing + delivery (E2-S1 / E2-S2).

Codes are issued synchronously so the caller can rely on the row existing;
delivery is handed to Celery so a slow mail server never blocks a request.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.authentication.models import OTP, OTPChannel
from apps.authentication.utils.otp import OTPService

OTP_TTL_MINUTES = 5

#: Channels with a delivery adapter this release. SMS is deferred (BRD §1.2).
DELIVERABLE_CHANNELS = (OTPChannel.EMAIL,)


def validate_channel(channel):
    """Reject a channel we cannot actually deliver on, rather than no-op."""
    if channel and channel not in DELIVERABLE_CHANNELS:
        raise ValidationError(
            {
                "channel": (
                    f"{channel} delivery is not available in this release. "
                    "Use EMAIL."
                )
            }
        )

    return channel or OTPChannel.EMAIL


class OTPDeliveryService:

    @transaction.atomic
    def issue(self, *, user, purpose, channel=OTPChannel.EMAIL):
        """Replace any live code for this purpose and queue a new one."""
        channel = validate_channel(channel)

        OTP.objects.filter(
            user=user,
            purpose=purpose,
            used_at__isnull=True,
        ).delete()

        code = OTPService.generate_otp()

        otp = OTP.objects.create(
            user=user,
            code_hash=OTPService.hash_otp(code),
            purpose=purpose,
            channel=channel,
            expires_at=timezone.now() + timedelta(minutes=OTP_TTL_MINUTES),
        )

        self.dispatch(user=user, code=code, purpose=purpose, channel=channel)

        return otp

    def dispatch(self, *, user, code, purpose, channel):
        """Queue delivery after the transaction commits.

        on_commit matters: without it the task can start before the OTP row is
        visible, and a fast worker would race the request that created it.
        """
        from apps.authentication.tasks import send_otp

        destination = user.email if channel == OTPChannel.EMAIL else None

        if not destination:
            raise ValidationError(
                {"channel": "No destination available for this channel."}
            )

        transaction.on_commit(
            lambda: send_otp.delay(
                destination=destination,
                code=code,
                purpose=str(purpose),
                channel=str(channel),
            )
        )
