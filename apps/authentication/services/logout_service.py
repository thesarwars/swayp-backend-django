from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import RefreshToken as RefreshTokenModel


class LogoutService:

    @staticmethod
    @transaction.atomic
    def logout(refresh_token: str):

        refresh = RefreshToken(refresh_token)

        RefreshTokenModel.objects.filter(
            user=refresh.user,
            revoked_at__isnull=True,
        ).update(
            revoked_at=timezone.now()
        )

        refresh.blacklist()