"""Occurrence-backed bill list (E4-S2)."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.bills.serializers.bill_occurrence_row_serializer import (
    BillOccurrenceRowSerializer,
)
from apps.bills.services.bill_service import BillService
from apps.common.pagination import StandardPagination
from apps.common.responses import ApiResponse


@extend_schema(
    tags=["Bills"],
    summary="List bill occurrences",
    description=(
        "The rows the bills screen shows. Each row is one due date, not one "
        "bill — status is computed from the due date at read time."
    ),
    parameters=[
        OpenApiParameter("status", str, description="UPCOMING|DUE|OVERDUE|SCHEDULED|PAID"),
        OpenApiParameter("vendor", str, description="Vendor id"),
        OpenApiParameter("date_from", str, description="YYYY-MM-DD"),
        OpenApiParameter("date_to", str, description="YYYY-MM-DD"),
    ],
    responses={200: BillOccurrenceRowSerializer(many=True)},
)
class BillOccurrenceListAPIView(APIView):

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillService()

    def get(self, request):
        queryset = self.service.list_occurrences(
            request.user,
            filters=request.query_params,
        )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)

        serializer = BillOccurrenceRowSerializer(page, many=True)

        body = paginator.get_paginated_response(serializer.data).data

        return ApiResponse.success(
            data=body["items"],
            message="Bill occurrences fetched successfully.",
            pagination=body["pagination"],
        )
