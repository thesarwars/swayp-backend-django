from django.db import transaction
from django.utils import timezone

from apps.authentication.services.login_service import LoginService


class LoginVerifyService:
    """Spend a LOGIN code and issue the session it stands for.

    Only phone login reaches this now. Email login stopped issuing LOGIN codes
    when the password became sufficient on its own; the phone flow still needs
    one, because a phone number is a claim and the code is what proves it.
    """

    @staticmethod
    @transaction.atomic
    def verify(user, otp_obj, request):
        otp_obj.used_at = timezone.now()
        otp_obj.save(update_fields=["used_at"])

        return LoginService.sign_in(user, request)
