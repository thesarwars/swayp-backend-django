from rest_framework import serializers

from apps.common.enums import NotificationType
from apps.notifications.channels import BY_FIELD


class NotificationChannelSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    supported = serializers.BooleanField()
    enabled = serializers.BooleanField()


class NotificationPreferenceSerializer(serializers.Serializer):
    type = serializers.CharField()
    label = serializers.CharField()
    inApp = serializers.BooleanField(source="in_app")
    email = serializers.BooleanField()
    sms = serializers.BooleanField()
    push = serializers.BooleanField()
    isDefault = serializers.BooleanField(source="is_default")


class NotificationPreferencesDataSerializer(serializers.Serializer):
    channels = NotificationChannelSerializer(many=True)
    preferences = NotificationPreferenceSerializer(many=True)


class NotificationPreferencesResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = NotificationPreferencesDataSerializer()


class NotificationPreferenceUpdateItemSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=NotificationType.choices)
    inApp = serializers.BooleanField(source="in_app", required=False)
    email = serializers.BooleanField(required=False)
    # sms/push are declared and refused rather than omitted: DRF drops unknown
    # keys silently, so a client toggling SMS would get 200 and no effect —
    # the silent-claim failure this story exists to prevent. false is accepted
    # so a client can send its whole state back alongside inApp/email, but it
    # cannot be the only thing an item names — see validate().
    sms = serializers.BooleanField(required=False)
    push = serializers.BooleanField(required=False)

    def validate_sms(self, value):
        if value:
            raise serializers.ValidationError(
                "SMS delivery is not available in this release."
            )

        return value

    def validate_push(self, value):
        if value:
            raise serializers.ValidationError(
                "Push delivery is not available in this release."
            )

        return value

    def validate(self, attrs):
        # At least one channel that has a delivery adapter — not merely at
        # least one key. sms/push can only ever be false (validate_sms and
        # validate_push refuse true), so an item naming only those is
        # indistinguishable from an item naming no channel at all: nothing
        # the user can perceive changes. Letting it through would still upsert
        # a row, which permanently flips isDefault to false for that type and
        # pins every other channel at today's defaults — destroying the
        # never-chose vs chose-the-default distinction that reading without
        # writing exists to preserve.
        if not set(attrs) & set(BY_FIELD):
            raise serializers.ValidationError(
                "At least one deliverable channel must be supplied."
            )

        return attrs


class NotificationPreferenceUpdateSerializer(serializers.Serializer):
    """Wraps the list in an object deliberately.

    apps/common/exception_handler.py only rebuilds the {success, message,
    errors} envelope when response.data is a dict; a top-level many=True
    serializer raises with a list and falls through to the raw DRF body.
    """

    preferences = NotificationPreferenceUpdateItemSerializer(
        many=True,
        allow_empty=False,
    )

    def validate_preferences(self, value):
        types = [item["type"] for item in value]

        if len(types) != len(set(types)):
            raise serializers.ValidationError(
                "Each notification type may appear only once."
            )

        return value
