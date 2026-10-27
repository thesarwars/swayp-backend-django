from django.db import transaction
from django.utils import timezone

from apps.authentication.models import OTPPurpose
from apps.authentication.services.login_service import LoginService
from apps.authentication.services.reset_token_service import (
    ResetTokenService,
)


class VerifyOTPService:

    @staticmethod
    @transaction.atomic
    def verify(user, otp_obj, request=None):

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

        # Through LoginService like every sign-in, so this first session is a
        # row the user can see and sign out like any other.
        return LoginService.login(user, request)
