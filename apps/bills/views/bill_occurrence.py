from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.bills.models.bill_occurrence import BillOccurrence
from apps.bills.serializers.bill_occurrence_serializer import BillOccurrenceSerializer
from apps.bills.serializers.bill_payment_serializer import BillPaymentSerializer
from apps.bills.services.bill_occurrence_service import BillOccurrenceService
from django.shortcuts import get_object_or_404
from rest_framework import status
from apps.teams.access import AccountScopedMixin


class UpcomingBillOccurrenceAPIView(AccountScopedMixin, APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillOccurrenceService()

    def get(self, request):
        occurrences = self.service.get_upcoming_occurrences(
            self.account(request)
        )

        serializer = BillOccurrenceSerializer(
            occurrences,
            many=True,
        )

        return Response(
            {
                "success": True,
                "message": "Upcoming bills fetched successfully.",
                "data": serializer.data,
            }
        )


class MarkBillOccurrencePaidAPIView(AccountScopedMixin, APIView):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = BillOccurrenceService()

    def patch(self, request, occurrence_id):
        serializer = BillPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        occurrence = get_object_or_404(
            BillOccurrence,
            id=occurrence_id,
            bill__user=self.account(request),
        )

        self.service.mark_as_paid(
            occurrence=occurrence,
            payment_reference=serializer.validated_data["payment_reference"],
        )

        return Response(
            {
                "success": True,
                "message": "Bill marked as paid successfully.",
                "data": None,
            },
            status=status.HTTP_200_OK,
        )