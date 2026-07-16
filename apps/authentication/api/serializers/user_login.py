from django.contrib.auth import authenticate, get_user_model
from django.utils import timezone
from rest_framework import serializers

from apps.authentication.models import OTP, OTPPurpose
from apps.authentication.utils.otp import OTPService

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs["email"].lower().strip()
        password = attrs["password"]

        user = authenticate(
            username=email,
            password=password,
        )

        if not user:
            raise serializers.ValidationError(
                {"detail": "Invalid email or password."}
            )

        if not user.is_active:
            raise serializers.ValidationError(
                {"detail": "Account is inactive."}
            )

        if not user.is_verified:
            raise serializers.ValidationError(
                {"detail": "Account is not verified."}
            )

        attrs["user"] = user

        return attrs


class LoginVerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(
        min_length=6,
        max_length=6,
    )

    def validate(self, attrs):
        email = attrs["email"].lower().strip()

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {"email": "User does not exist."}
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

        if otp_obj is None:
            raise serializers.ValidationError(
                {"otp": "OTP not found."}
            )

        if otp_obj.expires_at < timezone.now():
            raise serializers.ValidationError(
                {"otp": "OTP expired."}
            )

        if not OTPService.verify_otp(
            attrs["otp"],
            otp_obj.code_hash,
        ):
            otp_obj.attempts += 1
            otp_obj.save(update_fields=["attempts"])

            raise serializers.ValidationError(
                {"otp": "Invalid OTP."}
            )

        attrs["user"] = user
        attrs["otp_obj"] = otp_obj

        return attrs
