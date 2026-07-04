from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.hashers import make_password

from apps.authentication.models import RefreshToken as RefreshTokenModel


class LoginVerifyService:

    @staticmethod
    @transaction.atomic
    def verify(user, otp_obj, request):

        otp_obj.used_at = timezone.now()
        otp_obj.save(update_fields=["used_at"])

        refresh = RefreshToken.for_user(user)

        RefreshTokenModel.objects.create(
            user=user,
            token_hash = make_password(str(refresh)),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            ip_address=request.META.get("REMOTE_ADDR"),
            expires_at=timezone.now() + refresh.lifetime,
        )

        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }