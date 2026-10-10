from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.authentication.models import OTPChannel, OTPPurpose
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

        # A phone-change code is bound to the number it was requested for,
        # which this endpoint does not take. Resending one here would replace
        # the bound code with an unbound one the verify step must refuse.
        if purpose == OTPPurpose.PHONE_CHANGE:
            raise ValidationError(
                {
                    "purpose": [
                        "Request a new phone-change code from "
                        "users/profile/phone."
                    ]
                }
            )

        # Throttle first: a rejected resend must not invalidate the code the
        # user is already holding (E2-S2).
        OTPThrottleService().check(user=user, purpose=purpose)

        return OTPDeliveryService().issue(
            user=user,
            purpose=purpose,
            channel=channel,
        )
