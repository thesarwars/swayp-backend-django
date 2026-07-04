from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken


class VerifyOTPService:

    @staticmethod
    @transaction.atomic
    def verify(user, otp_obj):

        otp_obj.used_at = timezone.now()
        otp_obj.save(update_fields=["used_at"])

        user.is_verified = True
        user.is_active = True
        user.save(update_fields=["is_verified", "is_active"])

        refresh = RefreshToken.for_user(user)

        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }