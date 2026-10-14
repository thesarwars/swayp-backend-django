"""Adding or changing the account's phone number (AUTH-10).

The number is a login identifier — phone sign-in looks the account up by it —
so it cannot be a plain profile edit. Changing it takes two calls: request a
code, then spend it together with the number.

The code goes to the account's email, not to the new number. SMS delivery is
deferred this release (BRD §1.2), and phone sign-in sends its codes by email
for the same reason. What the code proves is that the person setting the
number controls the account's inbox, which is what stops a stolen session
from quietly attaching a number and signing in with it later.

The code is bound to the number it was requested for (``OTP.target``), so a
code requested for one number cannot be spent setting another.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.authentication.models import OTP, OTPChannel, OTPPurpose
from apps.authentication.services.otp_delivery_service import (
    OTPDeliveryService,
)
from apps.authentication.services.otp_throttle_service import (
    OTPThrottleService,
)
from apps.authentication.utils.otp import TOO_MANY_ATTEMPTS, OTPService
from apps.common.crypto import mask_email
from apps.common.error_codes import OTP_ATTEMPTS_EXCEEDED, OTP_NOT_PENDING

User = get_user_model()

NO_CODE = "No code is pending for this number. Request a new one."
EXPIRED = "Code expired. Request a new one."
INVALID = "Invalid code."
TAKEN = "This phone number is already in use."


class PhoneChangeService:

    def request(self, *, user, phone_number):
        self._assert_settable(user=user, phone_number=phone_number)

        # Throttled exactly like a resend: per user and purpose, 60 s apart,
        # five an hour. A rejected request leaves the live code alone.
        OTPThrottleService().check(user=user, purpose=OTPPurpose.PHONE_CHANGE)

        OTPDeliveryService().issue(
            user=user,
            purpose=OTPPurpose.PHONE_CHANGE,
            channel=OTPChannel.EMAIL,
            target=phone_number,
        )

        return {"email": mask_email(user.email)}

    def verify(self, *, user, phone_number, otp):
        otp_obj = (
            OTP.objects.filter(
                user=user,
                purpose=OTPPurpose.PHONE_CHANGE,
                used_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )

        if otp_obj is None or otp_obj.target != phone_number:
            raise ValidationError({"otp": [NO_CODE]}, code=OTP_NOT_PENDING)

        if otp_obj.expires_at < timezone.now():
            raise ValidationError({"otp": [EXPIRED]})

        if otp_obj.is_exhausted:
            raise ValidationError({"otp": [TOO_MANY_ATTEMPTS]}, code=OTP_ATTEMPTS_EXCEEDED)

        if not OTPService.verify_otp(otp, otp_obj.code):
            # Saved outside any transaction, so the count survives the error
            # this raises.
            otp_obj.attempts += 1
            otp_obj.save(update_fields=["attempts"])

            raise ValidationError({"otp": [INVALID]})

        # Checked again here: the number may have been taken by another
        # account between the request and now.
        self._assert_settable(user=user, phone_number=phone_number)

        try:
            with transaction.atomic():
                otp_obj.used_at = timezone.now()
                otp_obj.save(update_fields=["used_at"])

                user.phone_number = phone_number
                user.save(update_fields=["phone_number"])
        except IntegrityError:
            # Lost the race to the unique constraint. The code is not spent,
            # because the transaction rolled back with it.
            raise ValidationError({"phone_number": [TAKEN]})

        return user

    @staticmethod
    def _assert_settable(*, user, phone_number):
        if user.phone_number == phone_number:
            raise ValidationError(
                {"phone_number": ["This is already your phone number."]}
            )

        if (
            User.objects.filter(phone_number=phone_number)
            .exclude(pk=user.pk)
            .exists()
        ):
            raise ValidationError({"phone_number": [TAKEN]})
