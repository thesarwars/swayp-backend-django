from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bill_categories.serializers.next_due_serializer import (
    NextDueSerializer,
)
from apps.bill_categories.services.bill_occurrence_service import (
    BillOccurrenceService,
)


class NextDueAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillOccurrenceService()

    def get(self, request):
        occurrence = self.service.get_next_due(
            request.user
        )

        if occurrence is None:
            return Response(
                {
                    "success": True,
                    "message": "No upcoming bills found.",
                    "data": None,
                },
                status=status.HTTP_200_OK,
            )

        serializer = NextDueSerializer(occurrence)

        return Response(
            {
                "success": True,
                "message": "Next due bill fetched successfully.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )