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
from apps.reports.services.export_service import (
    MAX_EXPORT_ROWS,
    form_1099_export,
    payments_export,
)
from apps.reports.services.report_service import (
    PLAN_GATE_MESSAGE,
    ReportService,
)
from apps.teams.access import AccountScopedMixin
from apps.vendors.models.vendor import Vendor


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
        400: OpenApiResponse(description="Unsupported export format"),
        422: OpenApiResponse(description="Inverted date range"),
    },
)
class PaymentsReportAPIView(AccountScopedMixin, BaseAPIView):

    # pagination beside data in the schema (apps/common/schema.py).
    paginated_response = True
    """Query-time payments report (E8-S2)."""

    service_class = ReportService

    def get(self, request):
        query = ReportQuerySerializer(data=request.query_params)
        # An unrecognised ?export= is a 400 here, before any service work —
        # the format is validated rather than guessed at.
        query.is_valid(raise_exception=True)
        data = query.validated_data

        fmt = data.get("export")
        account = self.account(request)

        result = self.service.payments_report(
            user=account,
            vendor_id=data.get("vendor"),
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
            page=1 if fmt else data["page"],
            # An export is the whole filtered set, not the page the user
            # happened to be on. Capped, and the cap is disclosed in the file.
            page_size=MAX_EXPORT_ROWS if fmt else data["pageSize"],
        )

        if fmt:
            vendor_id = result["filters"].get("vendor")

            return payments_export(
                fmt=fmt,
                result=result,
                filters={
                    "date_from": data.get("date_from"),
                    "date_to": data.get("date_to"),
                    "vendor_name": (
                        Vendor.objects.filter(id=vendor_id)
                        .values_list("name", flat=True)
                        .first()
                        if vendor_id
                        else None
                    ),
                },
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
        400: OpenApiResponse(description="Unsupported export format"),
    },
)
class Form1099ReportAPIView(AccountScopedMixin, BaseAPIView):
    """Per-vendor annual totals for tax prep (E8-S2)."""

    service_class = ReportService

    def get(self, request):
        # Gate BEFORE parsing, deliberately. A Founding user asking for
        # ?export=csv must get the 403 that describes their situation, not a
        # 405 about a feature they cannot reach either way. The service gates
        # again — that one is the authority for any non-HTTP caller.
        if not has_plan_at_least(self.account(request), PlanCode.STANDARD):
            raise ForbiddenException(PLAN_GATE_MESSAGE)

        query = Form1099QuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        fmt = query.validated_data.get("export")

        result = self.service.vendor_1099(
            user=self.account(request), year=query.validated_data.get("year")
        )

        if fmt:
            return form_1099_export(fmt=fmt, result=result)

        return ApiResponse.success(
            data=Form1099ResponseSerializer(result).data,
            message="1099 vendor totals generated.",
        )
