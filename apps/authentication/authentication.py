"""JWT authentication that honours signed-out sessions.

simplejwt alone accepts an access token until it expires: nothing can recall
one. Checking the token's session on every request is what makes "sign out
this device" and "sign out everywhere" take effect immediately, instead of up
to ACCESS_TOKEN_LIFETIME later.
"""

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from apps.authentication.services.session_service import (
    SID_CLAIM,
    SessionService,
)


def session_is_live(token):
    """False only for a token whose session has ended. A token minted
    before sessions carried an id has nothing to check, and lapses on its
    own lifetime."""
    sid = token.get(SID_CLAIM)

    return sid is None or SessionService.is_live(sid)


class SessionJWTAuthentication(JWTAuthentication):

    def get_validated_token(self, raw_token):
        token = super().get_validated_token(raw_token)

        if not session_is_live(token):
            raise InvalidToken(
                {
                    "detail": "This session has been signed out.",
                    "code": "token_not_valid",
                }
            )

        return token
