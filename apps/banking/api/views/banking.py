"""Bank connection, scan and import endpoints (E5-S2 … E5-S6)."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status

from apps.banking.api.serializers.banking import (
    BankAccountSerializer,
    BankConnectionSerializer,
    BillDetectionCandidateSerializer,
    ImportCandidatesSerializer,
    LinkExchangeSerializer,
    LinkTokenSerializer,
    SetFundingSourceSerializer,
    StartScanSerializer,
    TransactionScanSerializer,
)
from apps.banking.selectors.onboarding_selector import OnboardingSelector
from apps.banking.services.connection_service import ConnectionService
from apps.banking.services.import_service import BillImportService
from apps.banking.services.link_service import BankLinkService
from apps.banking.services.scan_service import ScanService
from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.payments.idempotency import IdempotencyMixin


@extend_schema(
    tags=["Banking"],
    summary="Create a bank link token",
    description="Short-lived token the client hands to the bank link widget.",
    responses={200: LinkTokenSerializer},
)
class LinkTokenAPIView(BaseAPIView):

    service_class = BankLinkService

    def post(self, request):
        data = self.service.create_link_token(user=request.user)

        return ApiResponse.success(
            data=LinkTokenSerializer(data).data,
            message="Link token created.",
        )


@extend_schema(
    tags=["Banking"],
    summary="Exchange a public token for a connection",
    description=(
        "Stores the connection, its accounts and the consent timestamp, then "
        "starts a transaction scan. Consent is required."
    ),
    request=LinkExchangeSerializer,
    responses={201: BankConnectionSerializer},
)
class LinkExchangeAPIView(BaseAPIView):

    service_class = BankLinkService

    def post(self, request):
        serializer = LinkExchangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        connection = self.service.exchange(
            user=request.user,
            public_token=serializer.validated_data["public_token"],
            consent_accepted=serializer.validated_data["consent_accepted"],
        )

        # Linking a bank is only useful if we then look at it.
        scan = ScanService().start(
            user=request.user, connection_id=connection.id
        )

        body = BankConnectionSerializer(connection).data
        body["scan"] = TransactionScanSerializer(scan).data

        return ApiResponse.success(
            data=body,
            message="Bank connected.",
            status_code=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Banking"],
    summary="List bank connections",
    responses={200: BankConnectionSerializer(many=True)},
)
class BankConnectionListAPIView(BaseAPIView):

    service_class = ConnectionService

    def get(self, request):
        connections = self.service.list_connections(request.user)

        return ApiResponse.success(
            data=BankConnectionSerializer(connections, many=True).data,
            message="Connections fetched successfully.",
        )


@extend_schema(
    tags=["Banking"],
    summary="Disconnect a bank connection",
    description=(
        "Revokes the connection. Blocked while payments are in flight, since "
        "removing the funding source would strand them."
    ),
    responses={200: BankConnectionSerializer},
)
class BankConnectionDetailAPIView(BaseAPIView):

    service_class = ConnectionService

    def get(self, request, connection_id):
        connection = self.service.get_connection(request.user, connection_id)

        return ApiResponse.success(
            data=BankConnectionSerializer(connection).data,
            message="Connection fetched successfully.",
        )

    def delete(self, request, connection_id):
        connection = self.service.disconnect(
            user=request.user, connection_id=connection_id
        )

        return ApiResponse.success(
            data=BankConnectionSerializer(connection).data,
            message="Bank disconnected.",
        )


@extend_schema(
    tags=["Banking"],
    summary="List funding accounts",
    parameters=[
        OpenApiParameter("connection_id", str, description="Filter by connection"),
    ],
    responses={200: BankAccountSerializer(many=True)},
)
class BankAccountListAPIView(BaseAPIView):

    service_class = ConnectionService

    def get(self, request):
        accounts = self.service.list_accounts(
            request.user,
            connection_id=request.query_params.get("connection_id"),
        )

        return ApiResponse.success(
            data=BankAccountSerializer(accounts, many=True).data,
            message="Accounts fetched successfully.",
        )

    def post(self, request):
        """Choose the default funding source."""
        serializer = SetFundingSourceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        account = self.service.set_default_funding_source(
            user=request.user,
            account_id=serializer.validated_data["account_id"],
        )

        return ApiResponse.success(
            data=BankAccountSerializer(account).data,
            message="Default funding source updated.",
        )


@extend_schema(
    tags=["Banking"],
    summary="Start a transaction scan",
    request=StartScanSerializer,
    responses={202: TransactionScanSerializer},
)
class ScanStartAPIView(BaseAPIView):

    service_class = ScanService

    def post(self, request):
        serializer = StartScanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        scan = self.service.start(
            user=request.user,
            connection_id=serializer.validated_data["connection_id"],
            months=serializer.validated_data.get("months"),
        )

        return ApiResponse.success(
            data=TransactionScanSerializer(scan).data,
            message="Scan started.",
            status_code=status.HTTP_202_ACCEPTED,
        )


@extend_schema(
    tags=["Banking"],
    summary="Scan status",
    description="Poll this while the onboarding progress screen is open.",
    responses={200: TransactionScanSerializer},
)
class ScanDetailAPIView(BaseAPIView):

    service_class = ScanService

    def get(self, request, scan_id):
        scan = self.service.get_scan(user=request.user, scan_id=scan_id)

        return ApiResponse.success(
            data=TransactionScanSerializer(scan).data,
            message="Scan fetched successfully.",
        )


@extend_schema(
    tags=["Banking"],
    summary="Detected bill candidates",
    responses={200: BillDetectionCandidateSerializer(many=True)},
)
class ScanCandidateListAPIView(BaseAPIView):

    service_class = BillImportService

    def get(self, request, scan_id):
        candidates = self.service.candidates(
            user=request.user, scan_id=scan_id
        )

        return ApiResponse.success(
            data=BillDetectionCandidateSerializer(candidates, many=True).data,
            message="Candidates fetched successfully.",
        )


@extend_schema(
    tags=["Banking"],
    summary="Import detected bills",
    description=(
        "Creates a Vendor and Bill per candidate. Already-imported candidates "
        "are skipped and reported rather than duplicated, so a re-POST is a "
        "no-op. Honours the Idempotency-Key header."
    ),
    request=ImportCandidatesSerializer,
)
class ScanImportAPIView(IdempotencyMixin, BaseAPIView):

    service_class = BillImportService
    idempotency_endpoint = "banking.scan_import"

    def post(self, request, scan_id):
        serializer = ImportCandidatesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def handler():
            report = self.service.import_candidates(
                user=request.user,
                scan_id=scan_id,
                candidate_ids=serializer.validated_data.get("candidate_ids"),
                import_all=serializer.validated_data.get("all", False),
            )

            return ApiResponse.success(
                data=report,
                message=(
                    f"Imported {report['imported_count']} bill(s), "
                    f"skipped {report['skipped_count']}."
                ),
                status_code=status.HTTP_201_CREATED,
            )

        return self.run_idempotent(request, handler)


@extend_schema(
    tags=["Banking"],
    summary="Onboarding summary",
    description=(
        "Connected bank, detection counts, bill totals and per-vendor rail "
        "readiness. Bill figures come from the same selector the bills "
        "summary uses, so they reconcile by construction."
    ),
)
class OnboardingSummaryAPIView(BaseAPIView):

    def get(self, request):
        return ApiResponse.success(
            data=OnboardingSelector().summary(request.user),
            message="Onboarding summary fetched successfully.",
        )
