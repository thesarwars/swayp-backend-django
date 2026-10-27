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
        """Tokens, unconditionally. For a caller that has already proved
        everything: a completed MFA challenge, a password change, finishing
        registration."""
        return token_pair(SessionService.start(user, request))

    @staticmethod
    def sign_in(user, request):
        """What a sign-in path answers once the first factor checks out.

        Tokens, or — when the user has two-step verification on — no tokens
        and a challenge to finish at auth/login/mfa. Both shapes carry every
        key, so the client branches on ``mfa_required`` alone.
        """
        from apps.authentication.services.mfa_service import (
            METHODS,
            MFAChallenge,
            MFAService,
        )

        if MFAService.is_enabled(user):
            return {
                "access": None,
                "refresh": None,
                "mfa_required": True,
                "mfa_token": MFAChallenge.issue(user),
                "mfa_methods": list(METHODS),
            }

        return {
            **LoginService.login(user, request),
            "mfa_required": False,
            "mfa_token": None,
            "mfa_methods": [],
        }
