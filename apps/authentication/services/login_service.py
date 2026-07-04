from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.authentication.models import OTP, OTPPurpose
from apps.authentication.utils.otp import OTPService


class LoginService:

    @staticmethod
    @transaction.atomic
    def login(user):

        OTP.objects.filter(
            user=user,
            purpose=OTPPurpose.LOGIN,
            used_at__isnull=True,
        ).delete()

        otp = OTPService.generate_otp()

        OTP.objects.create(
            user=user,
            code_hash=OTPService.hash_otp(otp),
            purpose=OTPPurpose.LOGIN,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        # TODO: Send OTP using Email/SMS
        print(f"Login OTP: {otp}")