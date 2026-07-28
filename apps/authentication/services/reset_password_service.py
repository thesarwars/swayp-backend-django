from django.db import transaction
from django.utils import timezone

from apps.authentication.models import OTP, OTPPurpose
from apps.authentication.services.password_history_service import (
    PasswordHistoryService,
)


class ResetPasswordService:

    @staticmethod
    @transaction.atomic
    def reset(email, otp, password):

        user = (
            OTP.objects.select_related("user")
            .filter(
                user__email=email,
                purpose=OTPPurpose.RESET_PASSWORD,
                used_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )

        if not user:
            raise Exception("OTP not found.")

        otp_obj = user

        if otp_obj.expires_at < timezone.now():
            raise Exception("OTP expired.")

        from apps.authentication.utils.otp import OTPService

        if not OTPService.verify_otp(
            otp,
            otp_obj.code_hash,
        ):
            raise Exception("Invalid OTP.")

        account = otp_obj.user

        # Reject reuse before the OTP is consumed, so a rejected attempt does
        # not force the user to request a fresh code (E2-S4).
        history = PasswordHistoryService()
        history.assert_not_reused(user=account, raw_password=password)

        otp_obj.used_at = timezone.now()
        otp_obj.save(update_fields=["used_at"])

        # Record the outgoing hash before overwriting it.
        history.record(user=account)

        account.set_password(password)
        account.save(update_fields=["password"])

        return account