from rest_framework import serializers
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
