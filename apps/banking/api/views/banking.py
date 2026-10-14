"""Bank connection, scan and import endpoints (E5-S2 … E5-S6)."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status

from apps.common.exceptions import ProviderUnavailableException
from apps.banking.api.serializers.banking import (
    BankAccountSerializer,
    BankConnectionSerializer,
    BillDetectionCandidateSerializer,
    CandidateUpdateSerializer,
    ImportCandidatesSerializer,
    InstitutionSerializer,
    LinkExchangeSerializer,
    LinkedConnectionSerializer,
    LinkTokenRequestSerializer,
    LinkTokenSerializer,
    SetFundingSourceSerializer,
    StartScanSerializer,
    TransactionScanSerializer,
)
from apps.banking.api.serializers.onboarding import (
    ImportReportSerializer,
    ImportResponseSerializer,
    OnboardingSummaryResponseSerializer,
    OnboardingSummarySerializer,
)
from apps.banking.selectors.onboarding_selector import OnboardingSelector
from apps.banking.services.connection_service import ConnectionService
from apps.banking.services.import_service import BillImportService
from apps.banking.services.link_service import BankLinkService
from apps.banking.services.scan_service import ScanService
from apps.common.base_views import BaseAPIView
from apps.teams.access import AccountScopedMixin, RequiresCapability
from apps.teams.permissions import MANAGE_BANKS
from apps.common.responses import ApiResponse
from apps.payments.idempotency import IdempotencyMixin


@extend_schema(
    tags=["Banking"],
    summary="Search bank institutions",
    description=(
        "Institutions matching `search`, for a native bank picker. Plaid "
        "Link searches institutions in its own UI too — this is for clients "
        "that draw their own list."
    ),
    parameters=[
        OpenApiParameter(
            name="search",
            description="Free text, e.g. `chase`. Empty returns a default set.",
            required=False,
            type=str,
        )
    ],
    responses={200: InstitutionSerializer(many=True)},
)
class InstitutionSearchAPIView(AccountScopedMixin, BaseAPIView):
    """The native bank picker (1620-12323).

    Plaid Link already searches institutions in its own UI, so this exists
    only because the design draws its own list. It is scoped to the products
    Swayp needs, so the picker cannot offer a bank that fails at link time.
    """

    service_class = BankLinkService

    def get(self, request):
        query = (request.query_params.get("search") or "").strip()

        if not query:
            # Plaid refuses an empty query, and that surfaced as a 500 (web
            # B1). A picker opens before anyone types, so an empty search is
            # an empty list, not an error.
            return ApiResponse.success(
                data=[], message="Type a bank name to search."
            )

        try:
            institutions = self.service.search_institutions(query=query)
        except NotImplementedError as exc:
            # A provider that cannot search says so. Returning [] would read
            # as "no banks match" and send the user hunting for a typo.
            raise ProviderUnavailableException(str(exc)) from exc

        return ApiResponse.success(
            data=InstitutionSerializer(institutions, many=True).data,
            message="Institutions fetched successfully.",
        )


@extend_schema(
    tags=["Banking"],
    summary="Create a bank link token",
    description=(
        "Short-lived token the client hands to the bank link widget. Send "
        "`platform` (ios, android, web) so OAuth banks can return the user to "
        "the app: android gets the configured package name, ios and web the "
        "redirect URI. `expiration` is null on the mock provider. "
        "`months_history` is the window the scan will read."
    ),
    request=LinkTokenRequestSerializer,
    responses={200: LinkTokenSerializer},
)
class LinkTokenAPIView(AccountScopedMixin, BaseAPIView):

    service_class = BankLinkService

    def post(self, request):
        serializer = LinkTokenRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = self.service.create_link_token(
            user=self.account(request),
            platform=serializer.validated_data.get("platform"),
        )

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
    responses={201: LinkedConnectionSerializer},
)
class LinkExchangeAPIView(AccountScopedMixin, IdempotencyMixin, BaseAPIView):

    service_class = BankLinkService
    # Connecting a bank exposes the account's money (E10-S1).
    permission_classes = BaseAPIView.permission_classes + [
        RequiresCapability
    ]
    required_capability = MANAGE_BANKS

    def post(self, request):
        # A retry after a lost answer must not link the bank twice (API-2).
        return self.run_idempotent(request, lambda: self._exchange(request))

    def _exchange(self, request):
        serializer = LinkExchangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        connection = self.service.exchange(
            user=self.account(request),
            public_token=serializer.validated_data["public_token"],
            consent_accepted=serializer.validated_data["consent_accepted"],
        )

        # Linking a bank is only useful if we then look at it.
        scan = ScanService().start(
            user=self.account(request), connection_id=connection.id
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
class BankConnectionListAPIView(AccountScopedMixin, BaseAPIView):

    service_class = ConnectionService

    def get(self, request):
        connections = self.service.list_connections(self.account(request))

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
class BankConnectionDetailAPIView(AccountScopedMixin, BaseAPIView):

    service_class = ConnectionService

    @extend_schema(
        summary="A bank connection",
        description="One connection with its latest scan. 404 if not yours.",
        responses={200: BankConnectionSerializer},
    )
    def get(self, request, connection_id):
        connection = self.service.get_connection(self.account(request), connection_id)

        return ApiResponse.success(
            data=BankConnectionSerializer(connection).data,
            message="Connection fetched successfully.",
        )

    def delete(self, request, connection_id):
        connection = self.service.disconnect(
            user=self.account(request), connection_id=connection_id
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
class BankAccountListAPIView(AccountScopedMixin, BaseAPIView):

    service_class = ConnectionService

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "connection_id", OpenApiTypes.UUID, required=False,
                description="Only this connection's accounts.",
            )
        ],
        responses={200: BankAccountSerializer(many=True)},
    )
    def get(self, request):
        accounts = self.service.list_accounts(
            self.account(request),
            connection_id=request.query_params.get("connection_id"),
        )

        return ApiResponse.success(
            data=BankAccountSerializer(accounts, many=True).data,
            message="Accounts fetched successfully.",
        )

    @extend_schema(
        summary="Choose the default funding account",
        description=(
            "Payments debit this account unless they name another. An "
            "unknown or foreign account_id is a 400 on account_id."
        ),
        request=SetFundingSourceSerializer,
        responses={200: BankAccountSerializer},
    )
    def post(self, request):
        """Choose the default funding source."""
        serializer = SetFundingSourceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        account = self.service.set_default_funding_source(
            user=self.account(request),
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
class ScanStartAPIView(AccountScopedMixin, BaseAPIView):

    service_class = ScanService

    def post(self, request):
        serializer = StartScanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        scan = self.service.start(
            user=self.account(request),
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
class ScanDetailAPIView(AccountScopedMixin, BaseAPIView):

    service_class = ScanService

    def get(self, request, scan_id):
        scan = self.service.get_scan(user=self.account(request), scan_id=scan_id)

        return ApiResponse.success(
            data=TransactionScanSerializer(scan).data,
            message="Scan fetched successfully.",
        )


@extend_schema(
    tags=["Banking"],
    summary="Detected bill candidates",
    responses={200: BillDetectionCandidateSerializer(many=True)},
)
class ScanCandidateListAPIView(AccountScopedMixin, BaseAPIView):

    service_class = BillImportService

    def get(self, request, scan_id):
        candidates = self.service.candidates(
            user=self.account(request), scan_id=scan_id
        )

        return ApiResponse.success(
            data=BillDetectionCandidateSerializer(candidates, many=True).data,
            message="Candidates fetched successfully.",
        )


@extend_schema(
    tags=["Banking"],
    summary="Edit a detected bill before import",
    description=(
        "Partial update of amount, category, cadence and due_day — the fields "
        "import turns into the bill. Refused once the candidate is imported. "
        "Answers with the updated candidate."
    ),
    request=CandidateUpdateSerializer,
    responses={200: BillDetectionCandidateSerializer},
)
class ScanCandidateDetailAPIView(AccountScopedMixin, BaseAPIView):

    service_class = BillImportService

    def patch(self, request, scan_id, candidate_id):
        serializer = CandidateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        candidate = self.service.update_candidate(
            user=self.account(request),
            scan_id=scan_id,
            candidate_id=candidate_id,
            data=serializer.validated_data,
        )

        return ApiResponse.success(
            data=BillDetectionCandidateSerializer(candidate).data,
            message="Candidate updated.",
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
    responses={201: ImportResponseSerializer},
)
class ScanImportAPIView(AccountScopedMixin, IdempotencyMixin, BaseAPIView):

    service_class = BillImportService
    idempotency_endpoint = "banking.scan_import"

    def post(self, request, scan_id):
        serializer = ImportCandidatesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def handler():
            report = self.service.import_candidates(
                user=self.account(request),
                scan_id=scan_id,
                candidate_ids=serializer.validated_data.get("candidate_ids"),
                import_all=serializer.validated_data.get("all", False),
            )

            return ApiResponse.success(
                # Through the serializer, so amount is the "99.00" string
                # every money field is; the raw Decimal rendered as 99.0.
                data=ImportReportSerializer(report).data,
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
    responses={200: OnboardingSummaryResponseSerializer},
)
class OnboardingSummaryAPIView(AccountScopedMixin, BaseAPIView):

    def get(self, request):
        return ApiResponse.success(
            # Serialized so money renders as strings, as declared.
            data=OnboardingSummarySerializer(
                OnboardingSelector().summary(self.account(request))
            ).data,
            message="Onboarding summary fetched successfully.",
        )
