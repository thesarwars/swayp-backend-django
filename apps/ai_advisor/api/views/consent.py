from rest_framework import status
from rest_framework.response import Response

from apps.ai_advisor.api.serializers.consent import (
    ConsentInputSerializer,
    ConsentSerializer,
)
from apps.ai_advisor.services.consent_service import ConsentService
from apps.common.base_views import BaseAPIView
from apps.common.request_meta import request_meta


class AdvisorConsentAPIView(BaseAPIView):
    """Grant (POST) or revoke (DELETE) Flo advisor consent (E7-S1)."""

    def post(self, request):
        payload = ConsentInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        # request_meta consults X-Forwarded-For first: behind a load balancer
        # REMOTE_ADDR is the balancer, and a consent record naming the
        # balancer is not a record of who consented.
        consent = ConsentService.record(
            user=request.user,
            consent_text=payload.validated_data.get("consent_text") or None,
            **request_meta(request),
        )
        return Response(
            ConsentSerializer(consent).data, status=status.HTTP_200_OK
        )

    def delete(self, request):
        consent = ConsentService.revoke(
            user=request.user, **request_meta(request)
        )

        if consent is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response(
            ConsentSerializer(consent).data, status=status.HTTP_200_OK
        )
