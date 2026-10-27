from rest_framework import serializers

from apps.authentication.models import RefreshToken as Session


class SessionSerializer(serializers.ModelSerializer):
    """A signed-in device, for the "where you're signed in" screen."""

    signed_in_at = serializers.DateTimeField(source="created_at")
    current = serializers.SerializerMethodField()

    class Meta:
        model = Session
        fields = (
            "id",
            "user_agent",
            "ip_address",
            "signed_in_at",
            "last_used_at",
            "expires_at",
            "current",
        )

    def get_current(self, session) -> bool:
        return str(session.id) == self.context.get("current_sid")


class RevokeAllSessionsSerializer(serializers.Serializer):
    include_current = serializers.BooleanField(
        default=False,
        help_text=(
            "true signs this device out too. Default false: everywhere else."
        ),
    )


class RevokeAllSessionsResponseSerializer(serializers.Serializer):
    revoked = serializers.IntegerField(help_text="How many sessions ended.")
