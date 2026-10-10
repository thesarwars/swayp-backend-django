from rest_framework import serializers

from apps.common.casing import SnakeCaseInputMixin, snake_case_aliases
from apps.common.enums import NotificationType
from apps.notifications.channels import BY_FIELD


class NotificationChannelSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    supported = serializers.BooleanField()
    enabled = serializers.BooleanField()


@snake_case_aliases
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


class NotificationPreferenceUpdateItemSerializer(
    SnakeCaseInputMixin, serializers.Serializer
):
    type = serializers.ChoiceField(choices=NotificationType.choices)
    inApp = serializers.BooleanField(source="in_app", required=False)
    email = serializers.BooleanField(required=False)
    # sms/push are declared rather than omitted: DRF drops unknown keys
    # silently, so a client toggling one would get 200 and no effect — the
    # silent-claim failure this story exists to prevent. Whether switching one
    # ON is allowed is asked of the channel registry below, never hard-coded,
    # so registering an adapter is the single act that enables a channel.
    sms = serializers.BooleanField(required=False)
    push = serializers.BooleanField(required=False)

    @staticmethod
    def _refuse_unless_deliverable(field, label, value):
        """Reject switching on a channel with no adapter registered.

        Asked of BY_FIELD rather than written as a constant, so this guard
        disarms itself the moment a channel is registered instead of having
        to be found and deleted — the same reasoning as
        dedupe_key_is_storable() in the dispatch service. Push became
        deliverable in E8-S5 by exactly this route.
        """
        if value and field not in BY_FIELD:
            raise serializers.ValidationError(
                f"{label} delivery is not available in this release."
            )

        return value

    def validate_sms(self, value):
        return self._refuse_unless_deliverable("sms", "SMS", value)

    def validate_push(self, value):
        return self._refuse_unless_deliverable("push", "Push", value)

    def validate(self, attrs):
        # At least one channel that has a delivery adapter — not merely at
        # least one key. A channel with no adapter can only ever be false
        # (validate_sms / validate_push refuse true), so an item naming only
        # those is indistinguishable from one naming no channel at all: nothing
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
