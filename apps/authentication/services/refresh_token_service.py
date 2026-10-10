from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import RefreshToken as RefreshTokenModel

User = get_user_model()


def token_user(refresh):
    """The user a refresh token belongs to. simplejwt tokens carry the id
    in a claim, not a ``user`` attribute: reading ``refresh.user`` raised
    AttributeError, so every refresh and logout answered 500."""
    return User.objects.get(pk=refresh.payload[api_settings.USER_ID_CLAIM])


class RefreshTokenService:

    @staticmethod
    @transaction.atomic
    def refresh(tokens, request=None):
        """Record the session minted by TokenRefreshSerializer.

        ``tokens`` is the serializer's validated data: the new access token
        and, with ROTATE_REFRESH_TOKENS, the rotated refresh token (the old
        one is already blacklisted). Minting again here would hand out a
        second pair that no session row describes.
        """
        refresh = RefreshToken(tokens["refresh"])
        meta = request.META if request is not None else {}

        RefreshTokenModel.objects.create(
            user=token_user(refresh),
            token_hash=make_password(str(refresh)),
            user_agent=meta.get("HTTP_USER_AGENT", ""),
            ip_address=meta.get("REMOTE_ADDR"),
            expires_at=timezone.now() + refresh.lifetime,
        )

        return {
            "access": str(tokens["access"]),
            "refresh": str(refresh),
        }
