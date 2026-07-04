import re

from django.contrib.auth import get_user_model, authenticate
from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers
from django.utils import timezone
from rest_framework import serializers

from apps.authentication.models import OTP, OTPPurpose
from apps.authentication.utils.otp import OTPService

from apps.users.models import AccountType, User
from rest_framework_simplejwt.serializers import TokenRefreshSerializer


User = get_user_model()


class RegisterSerializer(serializers.Serializer):
    account_type = serializers.ChoiceField(
        choices=AccountType.choices
    )

    full_name = serializers.CharField(
        max_length=255
    )

    address = serializers.CharField()

    email = serializers.EmailField()

    phone_number = PhoneNumberField()

    password = serializers.CharField(
        write_only=True,
        min_length=12,
        style={"input_type": "password"},
    )

    confirm_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )

    business_name = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    poc_name = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    billing_address = serializers.CharField()

    def validate_email(self, value):
        value = value.lower().strip()

        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "Email already exists."
            )

        return value

    def validate_phone_number(self, value):
        if User.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError(
                "Phone number already exists."
            )

        return value

    def validate_password(self, value):

        if len(value) < 12:
            raise serializers.ValidationError(
                "Password must contain at least 12 characters."
            )

        if not re.search(r"[A-Z]", value):
            raise serializers.ValidationError(
                "Password must contain one uppercase letter."
            )

        if not re.search(r"[a-z]", value):
            raise serializers.ValidationError(
                "Password must contain one lowercase letter."
            )

        if not re.search(r"[0-9]", value):
            raise serializers.ValidationError(
                "Password must contain one digit."
            )

        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", value):
            raise serializers.ValidationError(
                "Password must contain one special character."
            )

        return value

    def validate(self, attrs):

        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {
                    "confirm_password": "Passwords do not match."
                }
            )

        account_type = attrs["account_type"]

        if account_type == AccountType.BUSINESS:

            if not attrs.get("business_name"):
                raise serializers.ValidationError(
                    {
                        "business_name": "This field is required."
                    }
                )

            if not attrs.get("poc_name"):
                raise serializers.ValidationError(
                    {
                        "poc_name": "This field is required."
                    }
                )

        return attrs
    

class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(
        min_length=6,
        max_length=6,
    )

    def validate(self, attrs):
        email = attrs["email"].lower()

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {"email": "User does not exist."}
            )

        otp_obj = (
            OTP.objects.filter(
                user=user,
                purpose=OTPPurpose.REGISTRATION,
                used_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )

        if not otp_obj:
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
    

class ResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()

    purpose = serializers.ChoiceField(
        choices=OTPPurpose.choices
    )

    def validate(self, attrs):
        email = attrs["email"].lower().strip()

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {"email": "User does not exist."}
            )

        attrs["user"] = user

        return attrs
    

class RefreshSerializer(TokenRefreshSerializer):
    pass

class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()