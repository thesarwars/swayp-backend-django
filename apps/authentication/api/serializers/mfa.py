from rest_framework import serializers

from apps.authentication.services.mfa_service import METHODS

from apps.authentication.api.serializers.token import TokenPairSerializer

CODE_HELP = "6 digits from the authenticator app, or a recovery code."


class MFAStatusSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    enabled_at = serializers.DateTimeField(allow_null=True)
    recovery_codes_remaining = serializers.IntegerField()


class MFASetupSerializer(serializers.Serializer):
    secret = serializers.CharField(
        help_text="For typing into the app when the QR code cannot be scanned."
    )
    otpauth_uri = serializers.CharField(
        help_text="Render as a QR code for the authenticator app to scan."
    )


class MFACodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32, help_text=CODE_HELP)


class MFAAppCodeSerializer(serializers.Serializer):
    code = serializers.CharField(
        max_length=32, help_text="6 digits from the authenticator app."
    )


class MFADisableSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32, help_text=CODE_HELP)
    password = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        help_text="Required unless the account signs in with Google only.",
    )


class RecoveryCodesSerializer(serializers.Serializer):
    recovery_codes = serializers.ListField(
        child=serializers.CharField(),
        help_text="Shown once. Each works one time in place of an app code.",
    )


class MFALoginSerializer(serializers.Serializer):
    mfa_token = serializers.CharField(help_text="From the sign-in response.")
    code = serializers.CharField(max_length=32, help_text=CODE_HELP)


class MFALoginResponseSerializer(TokenPairSerializer):
    mfa_method = serializers.ChoiceField(
        choices=METHODS,
        help_text="recovery_code: suggest making a new set.",
    )
