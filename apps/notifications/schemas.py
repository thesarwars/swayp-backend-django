from drf_spectacular.utils import extend_schema

from apps.common.swagger import (
    BAD_REQUEST_RESPONSE,
    NOT_FOUND_RESPONSE,
    UNAUTHORIZED_RESPONSE,
)

from .serializers import (
    MarkNotificationReadResponseSerializer,
    NotificationListResponseSerializer,
    NotificationQuerySerializer,
)


notification_list_schema = extend_schema(
    tags=["Notifications"],
    summary="List Notifications",
    description="Returns notifications for the authenticated user.",
    parameters=[NotificationQuerySerializer],
    responses={
        200: NotificationListResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
    },
)

notification_read_schema = extend_schema(
    tags=["Notifications"],
    summary="Mark Notification As Read",
    description="Marks a notification as read.",
    responses={
        200: MarkNotificationReadResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
    },
)

notification_read_all_schema = extend_schema(
    tags=["Notifications"],
    summary="Mark All Notifications As Read",
    description="Marks all unread notifications as read.",
    responses={
        200: MarkNotificationReadResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
    },
)