from apps.authentication.services.session_service import (
    SessionService,
    token_pair,
)


class LoginService:
    """Issuing a session — which is now the whole of email login.

    Login used to answer with an emailed code and hand the tokens out on a
    second call. It no longer does: a correct password is the login. The code
    added a step to every sign-in without adding a factor anyone had to hold
    separately, since it arrived in the same inbox that resets the password.

    The session row is what makes a sign-in listable and revocable later, so
    every path that mints tokens comes through here rather than minting its
    own.
    """

    @staticmethod
    def login(user, request):
        return token_pair(SessionService.start(user, request))
