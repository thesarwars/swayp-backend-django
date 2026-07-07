from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse

from .schemas import (
    notification_list_schema,
    notification_read_all_schema,
    notification_read_schema,
)
from .serializers import (
    NotificationQuerySerializer,
    NotificationSerializer,
)
from .services import NotificationService


class NotificationListAPIView(BaseAPIView):

    service_class = NotificationService

    @notification_list_schema  
    def get(self, request):
        query = NotificationQuerySerializer(
            data=request.query_params,
        )

        query.is_valid(raise_exception=True)

        result = self.service.list_notifications(
            user=request.user,
            page=query.validated_data["page"],
            page_size=query.validated_data["pageSize"],
        )

        serializer = NotificationSerializer(
            result["items"],
            many=True,
        )

        return ApiResponse.success(
            data=serializer.data,
            pagination=result["pagination"],
        )


class NotificationReadAPIView(BaseAPIView):

    service_class = NotificationService

    @notification_read_schema
    def patch(
        self,
        request,
        notification_id,
    ):
        self.service.mark_as_read(
            user=request.user,
            notification_id=notification_id,
        )

        return ApiResponse.success(
            message="Notification marked as read.",
        )


class NotificationReadAllAPIView(BaseAPIView):

    service_class = NotificationService

    @notification_read_all_schema
    def patch(self, request):
        self.service.mark_all_as_read(
            user=request.user,
        )

        return ApiResponse.success(
            message="All notifications marked as read.",
        )