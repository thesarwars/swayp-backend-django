"""Profile summary payload (D2).

The camelCase field names here are shipped and load-bearing. Every other
payload in the codebase is snake_case, so a future tidy-up will read these as
a mistake and "fix" them — that rename breaks the client. Leave them alone.
"""

from rest_framework import serializers

from apps.common.casing import snake_case_aliases


@snake_case_aliases
class ProfileSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()

    fullName = serializers.CharField(
        source="full_name"
    )

    profilePicture = serializers.CharField(
        source="profile_picture",
        allow_null=True,
    )

    greeting = serializers.ChoiceField(
        choices=[
            "Good Morning",
            "Good Afternoon",
            "Good Evening",
            "Good Night",
        ],
        help_text=(
            "Picked by the hour in US Eastern time: Morning 05-12, "
            "Afternoon 12-17, Evening 17-21, Night otherwise. A user in "
            "another timezone should be greeted by the device clock instead."
        ),
    )

    unreadNotificationCount = serializers.IntegerField(
        source="unread_notification_count"
    )


class ProfileSummaryResponseSerializer(
    serializers.Serializer
):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = ProfileSummarySerializer()
