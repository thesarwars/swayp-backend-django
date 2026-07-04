from django.db import transaction
from django.utils import timezone

from apps.authentication.models import OTP, OTPPurpose


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

        otp_obj.used_at = timezone.now()
        otp_obj.save(update_fields=["used_at"])

        account = otp_obj.user

        account.set_password(password)
        account.save(update_fields=["password"])

        return account