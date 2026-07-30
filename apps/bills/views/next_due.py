from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bills.serializers.next_due_serializer import (
    NextDueSerializer,
)
from apps.bills.services.bill_occurrence_service import (
    BillOccurrenceService,
)
from apps.teams.access import AccountScopedMixin


class NextDueAPIView(AccountScopedMixin, APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillOccurrenceService()

    def get(self, request):
        occurrence = self.service.get_next_due(
            self.account(request)
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