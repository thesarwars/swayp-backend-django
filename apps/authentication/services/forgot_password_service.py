from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.authentication.models import OTP, OTPPurpose
from apps.authentication.services.email_services import EmailService
from apps.authentication.utils.otp import OTPService


class ForgotPasswordService:

    @staticmethod
    @transaction.atomic
    def send(user):

        OTP.objects.filter(
            user=user,
            purpose=OTPPurpose.RESET_PASSWORD,
            used_at__isnull=True,
        ).delete()

        otp = OTPService.generate_otp()

        OTP.objects.create(
            user=user,
            code_hash=OTPService.hash_otp(otp),
            purpose=OTPPurpose.RESET_PASSWORD,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        try:
            EmailService.send_otp_email(user.email, otp, purpose="forgot_password")
        except Exception:
            print(f"Reset OTP: {otp}")