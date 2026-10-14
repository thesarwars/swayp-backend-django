"""Occurrence-backed bill list (E4-S2)."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.bills.serializers.bill_occurrence_row_serializer import (
    BillOccurrenceRowSerializer,
)
from apps.bills.services.bill_service import BillService
from apps.bills.selectors.bill_occurrence_selector import BillOccurrenceSelector
from apps.common.exceptions import NotFoundException
from apps.common.pagination import StandardPagination
from apps.common.responses import ApiResponse
from apps.common.swagger import NOT_FOUND_RESPONSE, UNAUTHORIZED_RESPONSE
from apps.teams.access import AccountScopedMixin


@extend_schema(
    tags=["Bills"],
    summary="List bill occurrences",
    description=(
        "The rows the bills screen shows. Each row is one due date, not one "
        "bill — status is computed from the due date at read time. Ordered "
        "by due_date, earliest first."
    ),
    parameters=[
        OpenApiParameter(
            "status",
            str,
            many=True,
            description=(
                "UPCOMING|DUE|OVERDUE|SCHEDULED|PAID. Several allowed, "
                "repeated or comma-separated."
            ),
        ),
        OpenApiParameter(
            "category",
            str,
            many=True,
            description=(
                "Category id. Several allowed, repeated or comma-separated."
            ),
        ),
        OpenApiParameter("vendor", str, description="Vendor id"),
        OpenApiParameter("bill", str, description="One bill's due dates."),
        OpenApiParameter(
            "search", str,
            description="Vendor name or bill notes contain this.",
        ),
        OpenApiParameter(
            "ordering", str,
            enum=["due_date", "-due_date", "amount", "-amount", "vendor",
                  "-vendor"],
            description="Default due_date (earliest first).",
        ),
        OpenApiParameter("date_from", str, description="YYYY-MM-DD"),
        OpenApiParameter("date_to", str, description="YYYY-MM-DD"),
        OpenApiParameter("page", int, description="Page number, from 1."),
        OpenApiParameter("page_size", int, description="Rows per page, up to 100."),
    ],
    responses={200: BillOccurrenceRowSerializer(many=True)},
)
class BillOccurrenceListAPIView(AccountScopedMixin, APIView):

    # pagination beside data in the schema (apps/common/schema.py).
    paginated_response = True

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillService()

    def get(self, request):
        queryset = self.service.list_occurrences(
            self.account(request),
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


@extend_schema(
    tags=["Bills"],
    summary="One bill occurrence",
    description=(
        "The same row the occurrence list returns, by id: bill_id, "
        "vendor_id, status, payment_id and the rest. For notification deep "
        "links that carry only an occurrence_id. 404 if it is not the "
        "account's."
    ),
    responses={
        200: BillOccurrenceRowSerializer,
        401: UNAUTHORIZED_RESPONSE,
        404: NOT_FOUND_RESPONSE,
    },
)
class BillOccurrenceDetailAPIView(AccountScopedMixin, APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, occurrence_id):
        occurrence = BillOccurrenceSelector().get_occurrence(
            self.account(request), occurrence_id
        )

        if occurrence is None:
            raise NotFoundException("Bill occurrence not found.")

        return ApiResponse.success(
            data=BillOccurrenceRowSerializer(occurrence).data,
            message="Bill occurrence fetched successfully.",
        )
