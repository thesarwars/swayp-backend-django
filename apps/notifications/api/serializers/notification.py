from rest_framework import serializers

from apps.common.casing import snake_case_aliases

from apps.common.enums import NotificationCategory, NotificationType
from apps.common.serializers import (
    PaginationQuerySerializer,
    PaginationResponseSerializer,
)


@snake_case_aliases
class NotificationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    message = serializers.CharField()
    # ChoiceField so OpenAPI publishes the enum (DASH-6). Output only, so it
    # never rejects a stored value.
    type = serializers.ChoiceField(choices=NotificationType.choices)
    isRead = serializers.BooleanField(source="is_read")
    createdAt = serializers.DateTimeField(source="created_at")
    readAt = serializers.DateTimeField(
        source="read_at",
        allow_null=True,
    )
    # The deep-link payload. Without it the column is write-only and the
    # client is back to parsing the message text, which is the exact thing it
    # exists to prevent (E8-S3). Id keys are uuid strings, or absent.
    metadata = serializers.JSONField(
        read_only=True,
        help_text=(
            "Deep-link ids, snake_case, each a uuid string or absent: "
            "bill_id, occurrence_id, payment_id, fee_charge_id. Which appear "
            "depends on type; see the e8 guide. May also carry display "
            "values (vendor_name, amount, reference, reason)."
        ),
    )


@snake_case_aliases
class NotificationListResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = NotificationSerializer(many=True)
    pagination = PaginationResponseSerializer(
        help_text=(
            "With ?before=, only pageSize and hasNext are present: a cursor "
            "page has no page number or total."
        )
    )
    nextCursor = serializers.UUIDField(
        allow_null=True,
        help_text="Pass as ?before= for the next page; null on the last.",
    )
    unreadCount = serializers.IntegerField(
        help_text="All unread notifications, ignoring the list's filters."
    )


class NotificationQuerySerializer(
    PaginationQuerySerializer
):
    # Repeatable: ?type=BILL_DUE&type=PAYMENT_FAILED.
    type = serializers.ListField(
        child=serializers.ChoiceField(choices=NotificationType.choices),
        required=False,
    )
    category = serializers.ChoiceField(
        choices=NotificationCategory.choices,
        required=False,
    )
    # Cursor paging (DASH-7): the rows older than this notification. When
    # sent, page is ignored; pass the previous response's nextCursor.
    before = serializers.UUIDField(required=False)
    # allow_null so an absent isRead means "both". Without it DRF reads a
    # missing boolean query param as false and the list would silently drop
    # every read notification.
    isRead = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
    )


@snake_case_aliases
class MarkNotificationReadResponseSerializer(
    serializers.Serializer
):
    """The updated row, and the badge count after the change (DASH-5)."""

    success = serializers.BooleanField()
    message = serializers.CharField()
    data = NotificationSerializer()
    unreadCount = serializers.IntegerField()


@snake_case_aliases
class MarkedCountSerializer(serializers.Serializer):
    markedCount = serializers.IntegerField(
        help_text="Notifications that were unread and are now read."
    )


@snake_case_aliases
class MarkAllReadResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = MarkedCountSerializer()
    unreadCount = serializers.IntegerField(help_text="Always 0.")