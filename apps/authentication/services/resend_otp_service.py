from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.authentication.models import OTP
from apps.authentication.services.email_services import EmailService
from apps.authentication.utils.otp import OTPService


class ResendOTPService:

    @staticmethod
    @transaction.atomic
    def resend(user, purpose):

        OTP.objects.filter(
            user=user,
            purpose=purpose,
            used_at__isnull=True,
        ).delete()

        otp = OTPService.generate_otp()

        OTP.objects.create(
            user=user,
            code_hash=OTPService.hash_otp(otp),
            purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        try:
            EmailService.send_otp_email(user.email, otp, purpose="registration" if purpose == "registration" else "login")
        except Exception:
            print(f"Resend OTP: {otp}")