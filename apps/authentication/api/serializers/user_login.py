from django.contrib.auth import authenticate, get_user_model
from django.utils import timezone
from rest_framework import serializers

from apps.authentication.models import OTP, OTPPurpose
from apps.authentication.services.lockout_service import LockoutService
from apps.authentication.utils.otp import OTPService

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs["email"].lower().strip()
        password = attrs["password"]

        # Looked up before authenticate() so the lock can be checked without
        # touching the password at all — otherwise response timing would tell
        # an attacker a locked account from a wrong password.
        known = User.objects.filter(email=email).first()
        lockout = LockoutService()

        if lockout.is_locked(known):
            raise serializers.ValidationError(
                {
                    "detail": (
                        "Too many failed attempts. Try again in "
                        f"{lockout.minutes_remaining(known)} minute(s)."
                    )
                }
            )

        user = authenticate(
            username=email,
            password=password,
        )

        if not user:
            # Counts against the known account when there is one, and does
            # nothing at all when there is not — creating or touching state
            # for an unknown email is how a lockout becomes a way to discover
            # who has an account.
            lockout.record_failure(known)

            raise serializers.ValidationError(
                {"detail": "Invalid email or password."}
            )

        # A correct password ends the sequence, even if the account was
        # inactive or unverified — those are different problems.
        lockout.record_success(user)

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
