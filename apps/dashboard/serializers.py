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