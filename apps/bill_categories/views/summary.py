from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bill_categories.serializers.bill_summary_serializer import (
    BillSummarySerializer,
)
from apps.bill_categories.services.bill_occurrence_service import (
    BillOccurrenceService,
)


class BillSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillOccurrenceService()

    def get(self, request):
        summary = self.service.get_summary(request.user)

        serializer = BillSummarySerializer(summary)

        return Response(
            {
                "success": True,
                "message": "Bills summary fetched successfully.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )