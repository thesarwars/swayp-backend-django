from django.contrib.auth import get_user_model
from rest_framework_simplejwt.settings import api_settings

from apps.authentication.services.session_service import SessionService

User = get_user_model()


def token_user(refresh):
    """The user a refresh token belongs to. simplejwt tokens carry the id
    in a claim, not a ``user`` attribute: reading ``refresh.user`` raised
    AttributeError, so every refresh and logout answered 500."""
    return User.objects.get(pk=refresh.payload[api_settings.USER_ID_CLAIM])


class RefreshTokenService:

    @staticmethod
    def refresh(tokens, request=None):
        """Record the session minted by TokenRefreshSerializer.

        ``tokens`` is the serializer's validated data: the new access token
        and, with ROTATE_REFRESH_TOKENS, the rotated refresh token (the old
        one is already blacklisted). Minting again here would hand out a
        second pair that no session row describes. Raises TokenError for a
        session that has been signed out.
        """
        return SessionService.rotated(tokens, request=request)
