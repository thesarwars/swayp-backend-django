from rest_framework import serializers

from apps.authentication.services.mfa_service import METHODS
from rest_framework_simplejwt.serializers import TokenRefreshSerializer


class RefreshSerializer(TokenRefreshSerializer):
    pass


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField(help_text="Bearer token for every call.")
    refresh = serializers.CharField(
        help_text="Rotates: store the new one each time."
    )


class SignInSerializer(serializers.Serializer):
    """A sign-in's answer: tokens, or an MFA challenge. Every key is always
    present; branch on mfa_required."""

    access = serializers.CharField(
        allow_null=True, help_text="null when mfa_required."
    )
    refresh = serializers.CharField(
        allow_null=True, help_text="null when mfa_required."
    )
    mfa_required = serializers.BooleanField(
        help_text="true: send mfa_token and a code to auth/login/mfa."
    )
    mfa_token = serializers.CharField(
        allow_null=True,
        help_text="The challenge to finish, valid 5 minutes and 5 tries.",
    )
    mfa_methods = serializers.ListField(
        child=serializers.ChoiceField(choices=METHODS),
        help_text="How the challenge can be answered; empty without MFA.",
    )
