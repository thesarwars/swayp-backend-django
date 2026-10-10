from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import RefreshToken as RefreshTokenModel
from apps.authentication.services.refresh_token_service import token_user


class LogoutService:

    @staticmethod
    @transaction.atomic
    def logout(refresh_token: str):
        try:
            refresh = RefreshToken(refresh_token)
        except TokenError as error:
            # An expired or already-blacklisted token is the client's
            # mistake, not a crash.
            raise ValidationError(
                {"refresh": "Token is invalid or expired."}
            ) from error

        RefreshTokenModel.objects.filter(
            user=token_user(refresh),
            revoked_at__isnull=True,
        ).update(
            revoked_at=timezone.now()
        )

        refresh.blacklist()
