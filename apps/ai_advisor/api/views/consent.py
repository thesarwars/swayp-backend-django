from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response

from apps.ai_advisor.api.serializers.consent import (
    ConsentInputSerializer,
    ConsentSerializer,
    ConsentStateSerializer,
)
from apps.ai_advisor.services.consent_service import ConsentService
from apps.common.base_views import BaseAPIView
from apps.common.request_meta import request_meta
from apps.common.responses import ApiResponse


@extend_schema(tags=["Flo (AI advisor)"])
class AdvisorConsentAPIView(BaseAPIView):
    """Read (GET), grant (POST), or revoke (DELETE) Flo consent (E7-S1)."""

    @extend_schema(
        summary="Read current Flo consent state",
        description=(
            "Whether Flo may use this user's financial data, plus the exact "
            "language they accepted. Returns is_live=false with null "
            "timestamps when the user has never consented, so a settings "
            "screen can render the toggle without granting anything."
        ),
        responses=ConsentStateSerializer,
    )
    def get(self, request):
        return ApiResponse.success(
            data=ConsentStateSerializer(
                ConsentService.state(request.user)
            ).data,
            message="Consent state retrieved.",
        )

    @extend_schema(
        summary="Grant Flo consent",
        description=(
            "Records the exact language shown to the user, with the "
            "originating client address, in the audit trail. Refused if that "
            "address cannot be determined. Re-posting while consent is "
            "already live is a no-op and preserves the original timestamp."
        ),
        request=ConsentInputSerializer,
        responses=ConsentSerializer,
    )
    def post(self, request):
        payload = ConsentInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        # request_meta consults X-Forwarded-For first: behind a load balancer
        # REMOTE_ADDR is the balancer, and a consent record naming the
        # balancer is not a record of who consented.
        consent = ConsentService.record(
            user=request.user,
            consent_text=payload.validated_data["consent_text"],
            **request_meta(request),
        )
        return ApiResponse.success(
            data=ConsentSerializer(consent).data,
            message="Consent recorded.",
        )

    @extend_schema(
        summary="Revoke Flo consent",
        description=(
            "Takes effect immediately — the gate is checked per request, so "
            "the next call makes no LLM call. Never refused; a revoke with "
            "nothing live returns 204."
        ),
        responses=ConsentSerializer,
    )
    def delete(self, request):
        consent = ConsentService.revoke(
            user=request.user, **request_meta(request)
        )

        if consent is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        return ApiResponse.success(
            data=ConsentSerializer(consent).data,
            message="Consent revoked.",
        )
