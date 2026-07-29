"""Report endpoints (E8-S2)."""

from drf_spectacular.utils import OpenApiResponse, extend_schema

from apps.common.base_views import BaseAPIView
from apps.common.enums import PlanCode
from apps.common.exceptions import ForbiddenException
from apps.common.plans import has_plan_at_least
from apps.common.responses import ApiResponse
from apps.common.swagger import UNAUTHORIZED_RESPONSE
from apps.reports.api.serializers.report import (
    Form1099QuerySerializer,
    Form1099ResponseSerializer,
    ReportQuerySerializer,
    ReportResponseSerializer,
)
from apps.reports.services.report_service import (
    PLAN_GATE_MESSAGE,
    ReportService,
)


@extend_schema(
    tags=["Reports"],
    summary="Payments report",
    description=(
        "Rows are payments; both filters are optional. `date` is the Eastern "
        "calendar date the payment was created — the same column payment "
        "history filters on — not the estimated arrival, which the processor "
        "rewrites at settlement. Cancelled payments never appear: the money "
        "provably never left. Totals cover the WHOLE filtered set, not the "
        "page. `export=` is refused with 405 until the format is decided "
        "(PRD §10-Q4)."
    ),
    parameters=[ReportQuerySerializer],
    responses={
        200: ReportResponseSerializer,
        401: UNAUTHORIZED_RESPONSE,
        404: OpenApiResponse(
            description="The vendor filter matches no vendor of yours"
        ),
        405: OpenApiResponse(description="Export is not supported yet"),
        422: OpenApiResponse(description="Inverted date range"),
    },
)
class PaymentsReportAPIView(BaseAPIView):
    """Query-time payments report (E8-S2)."""

    service_class = ReportService

    def get(self, request):
        query = ReportQuerySerializer(data=request.query_params)
        # ?export=... raises ExportNotSupportedException here, before any
        # service work and before any row is read.
        query.is_valid(raise_exception=True)
        data = query.validated_data

        result = self.service.payments_report(
            user=request.user,
            vendor_id=data.get("vendor"),
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
            page=data["page"],
            page_size=data["pageSize"],
        )

        # One message for both the populated and the empty case — totals.count
        # == 0 is the signal, so a client never branches on prose.
        return ApiResponse.success(
            data=ReportResponseSerializer(result).data,
            message="Report generated.",
            pagination=result["pagination"],
        )


@extend_schema(
    tags=["Reports"],
    summary="1099 vendor totals (Standard plan and above)",
    description=(
        "Per-vendor totals of SUCCESSFUL payments for a tax year. This is the "
        "DATA view, not form generation — form shape and the reporting "
        "threshold are open (PRD §10-Q4), so no threshold is applied and every "
        "vendor is returned. Plan-gated (BRD §6.2): 403 below Standard."
    ),
    parameters=[Form1099QuerySerializer],
    responses={
        200: Form1099ResponseSerializer,
        401: UNAUTHORIZED_RESPONSE,
        403: OpenApiResponse(description="Plan does not include 1099 reporting"),
        405: OpenApiResponse(description="Export is not supported yet"),
    },
)
class Form1099ReportAPIView(BaseAPIView):
    """Per-vendor annual totals for tax prep (E8-S2)."""

    service_class = ReportService

    def get(self, request):
        # Gate BEFORE parsing, deliberately. A Founding user asking for
        # ?export=csv must get the 403 that describes their situation, not a
        # 405 about a feature they cannot reach either way. The service gates
        # again — that one is the authority for any non-HTTP caller.
        if not has_plan_at_least(request.user, PlanCode.STANDARD):
            raise ForbiddenException(PLAN_GATE_MESSAGE)

        query = Form1099QuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        result = self.service.vendor_1099(
            user=request.user, year=query.validated_data.get("year")
        )

        return ApiResponse.success(
            data=Form1099ResponseSerializer(result).data,
            message="1099 vendor totals generated.",
        )
