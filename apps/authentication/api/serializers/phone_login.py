"""Phone-number sign-in (E2-S3).

Reuses OTPPurpose.LOGIN — no new purpose enum. Neither endpoint reveals whether
a phone number is registered: the request path always reports success, and the
verify path returns one generic error for "no such user", "no code" and "wrong
code" alike.
"""

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from apps.authentication.models import OTP, OTPChannel, OTPPurpose
from apps.authentication.utils.otp import OTPService

User = get_user_model()

GENERIC_VERIFY_ERROR = "Invalid phone number or code."


class PhoneLoginRequestSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=32)
    channel = serializers.ChoiceField(
        choices=OTPChannel.choices,
        required=False,
        default=OTPChannel.EMAIL,
    )

    def validate_phone_number(self, value):
        return value.strip()


class PhoneLoginVerifySerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=32)
    otp = serializers.CharField(min_length=6, max_length=6)

    def validate(self, attrs):
        phone_number = attrs["phone_number"].strip()

        user = User.objects.filter(phone_number=phone_number).first()

        if user is None:
            raise serializers.ValidationError(
                {"detail": GENERIC_VERIFY_ERROR}
            )

        otp_obj = (
            OTP.objects.filter(
                user=user,
                purpose=OTPPurpose.LOGIN,
                used_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )

        # An exhausted code answers with the same generic error: a distinct
        # message would confirm the number has an account.
        if (
            otp_obj is None
            or otp_obj.expires_at < timezone.now()
            or otp_obj.is_exhausted
        ):
            raise serializers.ValidationError(
                {"detail": GENERIC_VERIFY_ERROR}
            )

        if not OTPService.verify_otp(attrs["otp"], otp_obj.code):
            otp_obj.attempts += 1
            otp_obj.save(update_fields=["attempts"])

            raise serializers.ValidationError(
                {"detail": GENERIC_VERIFY_ERROR}
            )

        if not user.is_active:
            raise serializers.ValidationError(
                {"detail": "Account is inactive."}
            )

        attrs["user"] = user
        attrs["otp_obj"] = otp_obj

        return attrs
