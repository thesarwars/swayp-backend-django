from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.services.refresh_token_service import token_user
from apps.authentication.services.session_service import (
    SID_CLAIM,
    SessionService,
)


class LogoutService:

    @staticmethod
    @transaction.atomic
    def logout(refresh_token: str):
        """End the session this refresh token belongs to, and only that one.

        It used to mark every session row of the user's revoked, which did
        nothing while rows were not checked and would now sign out every
        other device: signing out everywhere is its own action
        (auth/sessions/revoke-all).
        """
        try:
            refresh = RefreshToken(refresh_token)
        except TokenError as error:
            # An expired or already-blacklisted token is the client's
            # mistake, not a crash.
            raise ValidationError(
                {"refresh": "Token is invalid or expired."}
            ) from error

        sid = refresh.get(SID_CLAIM)

        if sid is not None:
            SessionService.end(token_user(refresh), sid)

        refresh.blacklist()
