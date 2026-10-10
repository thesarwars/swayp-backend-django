from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        value = value.lower().strip()

        try:
            user = User.objects.get(email=value)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                "User does not exist."
            )

        self.user = user
        return value


class ResetPasswordVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(
        min_length=6,
        max_length=6,
    )


class ResetPasswordSerializer(serializers.Serializer):
    """Exactly one of ``otp`` and ``reset_token``.

    ``reset_token`` is what verify-otp returns for a RESET_PASSWORD code
    (AUTH-4). ``otp`` is the original one-step form, kept so a client that
    checks nothing early still works.
    """

    email = serializers.EmailField()

    otp = serializers.CharField(
        min_length=6,
        max_length=6,
        required=False,
    )

    reset_token = serializers.CharField(required=False)

    password = serializers.CharField(
        # min_length=12,
        write_only=True,
    )

    # confirm_password = serializers.CharField(
    #     write_only=True,
    # )

    def validate(self, attrs):
        if bool(attrs.get("otp")) == bool(attrs.get("reset_token")):
            raise serializers.ValidationError(
                "Send either otp or reset_token, not both."
                if attrs.get("otp")
                else "Send otp or reset_token."
            )

        return attrs

    # def validate(self, attrs):
    #     # if attrs["password"] != attrs["confirm_password"]:
    #     #     raise serializers.ValidationError(
    #     #         {
    #     #             "confirm_password": "Passwords do not match."
    #     #         }
    #     #     )

    #     return attrs
