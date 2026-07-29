from rest_framework import status
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import (
    IsAuthenticated,
)

from apps.vendors.models import Vendor
from apps.common.enums import VendorSource, VendorStatus
from apps.vendors.api.serializers.vendor_payment_method import (
    PaymentMethodScheduleQuerySerializer,
    VendorPaymentMethodSerializer,
    VendorPaymentMethodCreateSerializer,
)

from apps.vendors.models.vendor_payment_method import VendorPaymentMethod
from apps.vendors.services.vendor_service import (

    VendorPaymentMethodService,

)

from apps.vendors.selectors.vendor_selector import (

    VendorSelector,

)
from apps.teams.access import AccountScopedMixin


class VendorPaymentMethodListCreateAPIView(AccountScopedMixin, ListCreateAPIView):
    """
    GET  /vendors/{vendor_id}/payment-methods/?due_date=&amount=
    POST /vendors/{vendor_id}/payment-methods/

    ``due_date`` turns on the per-method schedule block that the bill wizard's
    method step reads (E3-S6 → E4-S3). ``amount`` is validated and accepted for
    forward compatibility but does not yet change the schedule — per-payment
    fees and same-day limits arrive with E9.
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return VendorSelector.payment_methods(
            user=self.account(self.request),
            vendor_id=self.kwargs["vendor_id"],
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return VendorPaymentMethodCreateSerializer

        return VendorPaymentMethodSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()

        if self.request.method != "GET":
            return context

        query = PaymentMethodScheduleQuerySerializer(
            data=self.request.query_params
        )
        query.is_valid(raise_exception=True)

        context["due_date"] = query.validated_data.get("due_date")
        context["amount"] = query.validated_data.get("amount")

        return context

    def create(self, request, *args, **kwargs):

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        vendor = get_object_or_404(
            Vendor,
            id=self.kwargs["vendor_id"],
            user=self.account(request),
            status=VendorStatus.ACTIVE,
        )

        payment_method = VendorPaymentMethodService.create(
            vendor=vendor,
            validated_data=serializer.validated_data,
        )

        response = VendorPaymentMethodSerializer(payment_method)

        return Response(
            response.data,
            status=status.HTTP_201_CREATED,
        )


class VendorPaymentMethodDetailAPIView(AccountScopedMixin, RetrieveUpdateDestroyAPIView):
    """
    GET
    PUT/PATCH
    DELETE
    """

    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = "method_id"

    def get_queryset(self):
        return VendorSelector.payment_methods(
            user=self.account(self.request),
            vendor_id=self.kwargs["vendor_id"],
        )

    def get_serializer_class(self):
        if self.request.method in ["PUT", "PATCH"]:
            return VendorPaymentMethodCreateSerializer

        return VendorPaymentMethodSerializer

    def perform_update(self, serializer):

        VendorPaymentMethodService.update(
            payment_method=serializer.instance,
            validated_data=serializer.validated_data,
        )

    def perform_destroy(self, instance):

        VendorPaymentMethodService.delete(instance)


class SetPrimaryPaymentMethodAPIView(AccountScopedMixin, APIView):
    """
    POST
    /vendors/{vendor_id}/payment-methods/{method_id}/set-primary/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, vendor_id, method_id):

        payment_method = get_object_or_404(
            VendorPaymentMethod,
            id=method_id,
            vendor__id=vendor_id,
            vendor__user=self.account(request),
            vendor__status=VendorStatus.ACTIVE,
        )

        VendorPaymentMethodService.set_primary(
            payment_method
        )

        return Response(
            {
                "message": "Primary payment method updated."
            },
            status=status.HTTP_200_OK,
        )