from django.db import transaction

from apps.authentication.services.login_service import LoginService
from apps.authentication.services.password_history_service import (
    PasswordHistoryService,
)
from apps.authentication.services.reset_password_service import (
    ResetPasswordService,
)


class ChangePasswordService:
    """Change the password of a signed-in user (web §4).

    Same rules as a reset: the new password may not reuse the previous one,
    and every other session ends, since changing a password is how someone
    shuts out a device they no longer trust. The caller gets a fresh token
    pair so this device stays signed in.
    """

    @staticmethod
    def change(*, user, new_password, request):
        history = PasswordHistoryService()
        history.assert_not_reused(user=user, raw_password=new_password)

        with transaction.atomic():
            history.record(user=user)
            user.set_password(new_password)
            user.save(update_fields=["password"])
            ResetPasswordService._end_sessions(user)

        return LoginService.login(user, request)
