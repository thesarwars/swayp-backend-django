from django.db import transaction

from apps.authentication.models import OTPChannel, OTPPurpose
from apps.authentication.services.otp_delivery_service import (
    OTPDeliveryService,
)


class ForgotPasswordService:

    @staticmethod
    @transaction.atomic
    def send(user, channel=OTPChannel.EMAIL):
        return OTPDeliveryService().issue(
            user=user,
            purpose=OTPPurpose.RESET_PASSWORD,
            channel=channel,
        )
