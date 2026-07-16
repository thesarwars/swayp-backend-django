from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenRefreshSerializer


class RefreshSerializer(TokenRefreshSerializer):
    pass


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
