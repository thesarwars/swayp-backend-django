from django.db import transaction

from apps.authentication.models import OTPChannel, OTPPurpose
from apps.authentication.services.otp_delivery_service import (
    OTPDeliveryService,
)


class LoginService:

    @staticmethod
    @transaction.atomic
    def login(user, channel=OTPChannel.EMAIL):
        return OTPDeliveryService().issue(
            user=user,
            purpose=OTPPurpose.LOGIN,
            channel=channel,
        )
