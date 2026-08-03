from rest_framework import serializers

from apps.notifications.models import DevicePlatform, DeviceToken


class DeviceRegisterSerializer(serializers.Serializer):
    """A device asking to be reachable by push (E8-S5)."""

    token = serializers.CharField(max_length=512)
    platform = serializers.ChoiceField(choices=DevicePlatform.choices)
    deviceName = serializers.CharField(
        source="device_name",
        max_length=120,
        required=False,
        allow_blank=True,
        default="",
    )

    def validate_token(self, value):
        # Whitespace is the common shape of a broken client: a token pasted
        # with a trailing newline registers, then never receives anything,
        # and the row looks perfectly healthy while doing so.
        value = value.strip()

        if not value:
            raise serializers.ValidationError("Token must not be blank.")

        return value


class DeviceUnregisterSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=512)


class DeviceSerializer(serializers.ModelSerializer):
    """Never echoes the token back — see the view."""

    deviceName = serializers.CharField(source="device_name")
    isActive = serializers.BooleanField(source="is_active")
    lastSeenAt = serializers.DateTimeField(source="last_seen_at")

    class Meta:
        model = DeviceToken
        fields = ("id", "platform", "deviceName", "isActive", "lastSeenAt")
