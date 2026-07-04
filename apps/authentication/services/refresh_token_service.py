from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone

from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import RefreshToken as RefreshTokenModel


class RefreshTokenService:

    @staticmethod
    @transaction.atomic
    def refresh(refresh_token: str):

        refresh = RefreshToken(refresh_token)

        user = refresh.user

        RefreshTokenModel.objects.create(
            user=user,
            token_hash=make_password(str(refresh)),
            user_agent="",
            ip_address="127.0.0.1",
            expires_at=timezone.now() + refresh.lifetime,
        )

        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }