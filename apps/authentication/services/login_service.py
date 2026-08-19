from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import RefreshToken as RefreshTokenModel


class LoginService:
    """Issuing a session — which is now the whole of email login.

    Login used to answer with an emailed code and hand the tokens out on a
    second call. It no longer does: a correct password is the login. The code
    added a step to every sign-in without adding a factor anyone had to hold
    separately, since it arrived in the same inbox that resets the password.

    The row written here is what makes a session revocable and identifiable
    later, so it is recorded on every path that mints tokens rather than only
    on the one that used to.
    """

    @staticmethod
    @transaction.atomic
    def login(user, request):
        refresh = RefreshToken.for_user(user)

        RefreshTokenModel.objects.create(
            user=user,
            token_hash=make_password(str(refresh)),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            ip_address=request.META.get("REMOTE_ADDR"),
            expires_at=timezone.now() + refresh.lifetime,
        )

        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }
