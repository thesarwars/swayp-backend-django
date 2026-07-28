from django.db import transaction

from apps.authentication.models import OTPChannel
from apps.authentication.services.otp_delivery_service import (
    OTPDeliveryService,
    validate_channel,
)
from apps.authentication.services.otp_throttle_service import (
    OTPThrottleService,
)


class ResendOTPService:

    @staticmethod
    @transaction.atomic
    def resend(user, purpose, channel=OTPChannel.EMAIL):
        channel = validate_channel(channel)

        # Throttle first: a rejected resend must not invalidate the code the
        # user is already holding (E2-S2).
        OTPThrottleService().check(user=user, purpose=purpose)

        return OTPDeliveryService().issue(
            user=user,
            purpose=purpose,
            channel=channel,
        )
