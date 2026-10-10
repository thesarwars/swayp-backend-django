"""OTP issuing + delivery (E2-S1 / E2-S2).

Codes are issued synchronously so the caller can rely on the row existing;
delivery is handed to Celery so a slow mail server never blocks a request.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.authentication.models import OTP, OTPChannel
from apps.authentication.utils.otp import OTPService
from apps.common.exceptions import ChannelNotAvailableException

logger = logging.getLogger(__name__)

OTP_TTL_MINUTES = 5

#: Channels with a delivery adapter this release. SMS is deferred (BRD §1.2).
DELIVERABLE_CHANNELS = (OTPChannel.EMAIL,)


def validate_channel(channel):
    """Reject a channel we cannot actually deliver on, rather than no-op.

    501 (not 400): the request is well-formed, SMS just isn't implemented
    this release.
    """
    if channel and channel not in DELIVERABLE_CHANNELS:
        raise ChannelNotAvailableException(
            f"{channel} delivery is not available in this release. Use EMAIL."
        )

    return channel or OTPChannel.EMAIL


class OTPDeliveryService:

    @transaction.atomic
    def issue(self, *, user, purpose, channel=OTPChannel.EMAIL, target=""):
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
            target=target,
            expires_at=timezone.now() + timedelta(minutes=OTP_TTL_MINUTES),
        )

        self.dispatch(user=user, code=code, purpose=purpose, channel=channel)

        return otp

    def dispatch(self, *, user, code, purpose, channel):
        """Queue delivery after the transaction commits.

        on_commit matters: without it the task can start before the OTP row is
        visible, and a fast worker would race the request that created it.
        """
        destination = user.email if channel == OTPChannel.EMAIL else None

        if not destination:
            # Was `raise ValidationError(...)` with no import left after the
            # switch to ChannelNotAvailableException, so this path raised
            # NameError instead of the error it meant to.
            raise ChannelNotAvailableException(
                f"No destination available for {channel} delivery."
            )

        transaction.on_commit(
            lambda: self._queue_or_send(
                destination=destination,
                code=code,
                purpose=str(purpose),
                channel=str(channel),
            )
        )

    def _queue_or_send(self, *, destination, code, purpose, channel):
        """Hand the OTP to Celery, falling back to sending it inline.

        A broker that is down, unreachable or version-incompatible must not
        cost the user their code. Before this, a failed ``.delay()`` meant the
        request still answered "OTP has been sent" while nothing was ever
        delivered — the worst possible outcome, because the user waits for an
        email that does not exist.

        Sending inline is slower and blocks the request, which is exactly why
        it is the fallback and not the default. The failure is logged at error
        level so a broken broker is visible rather than silently absorbed.
        """
        from apps.authentication.tasks import send_otp

        payload = {
            "destination": destination,
            "code": code,
            "purpose": purpose,
            "channel": channel,
        }

        try:
            return send_otp.delay(**payload)
        except Exception as exc:
            logger.error(
                "OTP could not be queued (%s: %s) — sending inline so the "
                "user still receives it. Check the Celery broker.",
                type(exc).__name__,
                exc,
            )

        # Run the task body directly. Any delivery error propagates, so a
        # genuinely undeliverable address still surfaces as an error rather
        # than a false success.
        return send_otp(**payload)
