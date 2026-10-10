from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.authentication.models import OTP, OTPPurpose
from apps.authentication.services.password_history_service import (
    PasswordHistoryService,
)
from apps.authentication.services.reset_token_service import (
    ResetTokenService,
)
from apps.authentication.utils.otp import TOO_MANY_ATTEMPTS, OTPService

#: Also the answer for an email with no account, so this endpoint cannot be
#: used to find out who is registered.
NO_CODE = "No reset code is pending. Request a new one."


class ResetPasswordService:

    @staticmethod
    def reset(email, otp, password, reset_token=None):
        if reset_token:
            # The code was already checked and spent at verify-otp. The token
            # dies when the password below changes, so it is single-use.
            account = ResetTokenService.resolve(email=email, token=reset_token)
            otp_obj = None
        else:
            otp_obj = ResetPasswordService._check_code(email, otp)
            account = otp_obj.user

        # Reject reuse before the OTP is consumed, so a rejected attempt does
        # not force the user to request a fresh code (E2-S4).
        history = PasswordHistoryService()
        history.assert_not_reused(user=account, raw_password=password)

        with transaction.atomic():
            if otp_obj is not None:
                otp_obj.used_at = timezone.now()
                otp_obj.save(update_fields=["used_at"])

            # Record the outgoing hash before overwriting it.
            history.record(user=account)

            account.set_password(password)
            account.save(update_fields=["password"])

            ResetPasswordService._end_sessions(account)

        return account

    @staticmethod
    def _end_sessions(account):
        """Sign out every session (SEC-5). A reset is often how someone takes
        an account back; leaving the old refresh tokens alive would let
        whoever held one carry on for weeks. Access tokens cannot be
        recalled and lapse on their own lifetime."""
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )

        from apps.authentication.models import RefreshToken

        RefreshToken.objects.filter(
            user=account, revoked_at__isnull=True
        ).update(revoked_at=timezone.now())

        for outstanding in OutstandingToken.objects.filter(user=account):
            BlacklistedToken.objects.get_or_create(token=outstanding)

    @staticmethod
    def _check_code(email, otp):
        # Not one transaction: a wrong guess has to be counted, and an error
        # raised inside an atomic block would roll the count back with it.
        otp_obj = (
            OTP.objects.select_related("user")
            .filter(
                user__email=email,
                purpose=OTPPurpose.RESET_PASSWORD,
                used_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )

        if otp_obj is None:
            raise ValidationError({"otp": [NO_CODE]})

        if otp_obj.expires_at < timezone.now():
            raise ValidationError({"otp": ["OTP expired. Request a new one."]})

        if otp_obj.is_exhausted:
            raise ValidationError({"otp": [TOO_MANY_ATTEMPTS]})

        if not OTPService.verify_otp(otp, otp_obj.code_hash):
            otp_obj.attempts += 1
            otp_obj.save(update_fields=["attempts"])

            raise ValidationError({"otp": ["Invalid OTP."]})

        return otp_obj
