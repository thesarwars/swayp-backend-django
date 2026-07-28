from rest_framework import status
from rest_framework.response import Response

from apps.ai_advisor.api.serializers.consent import (
    ConsentInputSerializer,
    ConsentSerializer,
)
from apps.ai_advisor.services.consent_service import ConsentService
from apps.common.base_views import BaseAPIView


def _client(request):
    return (
        request.META.get("REMOTE_ADDR"),
        request.META.get("HTTP_USER_AGENT", ""),
    )


class AdvisorConsentAPIView(BaseAPIView):
    """Grant (POST) or revoke (DELETE) Flo advisor consent (E7-S1)."""

    def post(self, request):
        payload = ConsentInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        ip, user_agent = _client(request)
        consent = ConsentService.record(
            user=request.user,
            consent_text=payload.validated_data.get("consent_text") or None,
            ip=ip,
            user_agent=user_agent,
        )
        return Response(
            ConsentSerializer(consent).data, status=status.HTTP_200_OK
        )

    def delete(self, request):
        ip, user_agent = _client(request)
        consent = ConsentService.revoke(
            user=request.user, ip=ip, user_agent=user_agent
        )

        if consent is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response(
            ConsentSerializer(consent).data, status=status.HTTP_200_OK
        )
