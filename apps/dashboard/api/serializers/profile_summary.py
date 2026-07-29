"""Profile summary payload (D2).

The camelCase field names here are shipped and load-bearing. Every other
payload in the codebase is snake_case, so a future tidy-up will read these as
a mistake and "fix" them — that rename breaks the client. Leave them alone.
"""

from rest_framework import serializers


class ProfileSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()

    fullName = serializers.CharField(
        source="full_name"
    )

    profilePicture = serializers.CharField(
        source="profile_picture",
        allow_null=True,
    )

    greeting = serializers.CharField()

    unreadNotificationCount = serializers.IntegerField(
        source="unread_notification_count"
    )


class ProfileSummaryResponseSerializer(
    serializers.Serializer
):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = ProfileSummarySerializer()
