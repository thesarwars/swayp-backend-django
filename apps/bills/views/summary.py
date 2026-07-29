from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bills.serializers.bill_summary_serializer import (
    BillSummarySerializer,
)
from apps.bills.services.bill_occurrence_service import (
    BillOccurrenceService,
)
from apps.teams.access import AccountScopedMixin


class BillSummaryAPIView(AccountScopedMixin, APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillOccurrenceService()

    def get(self, request):
        summary = self.service.get_summary(self.account(request))

        serializer = BillSummarySerializer(summary)

        return Response(
            {
                "success": True,
                "message": "Bills summary fetched successfully.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )