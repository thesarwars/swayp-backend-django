from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import OTPPurpose
from apps.authentication.services.reset_token_service import (
    ResetTokenService,
)


class VerifyOTPService:

    @staticmethod
    @transaction.atomic
    def verify(user, otp_obj):

        otp_obj.used_at = timezone.now()
        otp_obj.save(update_fields=["used_at"])

        # A reset code proves the inbox, not the password, so it must not
        # sign anyone in or activate an account. It buys a reset token and
        # nothing else (AUTH-4).
        if otp_obj.purpose == OTPPurpose.RESET_PASSWORD:
            return ResetTokenService.issue(user)

        user.is_verified = True
        user.is_active = True
        user.save(update_fields=["is_verified", "is_active"])

        refresh = RefreshToken.for_user(user)

        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }
