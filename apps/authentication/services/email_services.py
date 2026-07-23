import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


class EmailService:

    @staticmethod
    def send_otp_email(email, otp, purpose="registration"):
        purpose_label = {
            "registration": "Verify Your Swayp Account",
            "forgot_password": "Reset Your Swayp Password",
            "login": "Your Swayp Login OTP",
        }.get(purpose, "Swayp OTP")

        subject = f"{purpose_label}"
        message = f"""Hello,

This is your Swayp verification code:

{otp}

It will expire in 10 minutes.

Thanks,
Swayp Team
"""

        if purpose == "forgot_password":
            message = f"""Hello,

You requested a password reset for your Swayp account.

Your verification code is:

{otp}

It will expire in 10 minutes.

Thanks,
Swayp Team
"""
        elif purpose == "login":
            message = f"""Hello,

We received a login request for your Swayp account.

Your verification code is:

{otp}

It will expire in 10 minutes.

Thanks,
Swayp Team
"""

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL or settings.EMAIL_HOST_USER,
                recipient_list=[email],
                fail_silently=False,
            )
            return True
        except Exception as exc:
            logger.exception("Failed to send OTP email to %s", email)
            raise exc

    @staticmethod
    def send_registration_otp(email, otp):
        EmailService.send_otp_email(email, otp, purpose="registration")