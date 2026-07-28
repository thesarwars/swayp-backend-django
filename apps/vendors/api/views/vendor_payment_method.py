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


class VendorPaymentMethodListCreateAPIView(ListCreateAPIView):
    """
    GET  /vendors/{vendor_id}/payment-methods/
    POST /vendors/{vendor_id}/payment-methods/
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return VendorSelector.payment_methods(
            user=self.request.user,
            vendor_id=self.kwargs["vendor_id"],
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return VendorPaymentMethodCreateSerializer

        return VendorPaymentMethodSerializer

    def create(self, request, *args, **kwargs):

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        vendor = get_object_or_404(
            Vendor,
            id=self.kwargs["vendor_id"],
            user=request.user,
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


class VendorPaymentMethodDetailAPIView(RetrieveUpdateDestroyAPIView):
    """
    GET
    PUT/PATCH
    DELETE
    """

    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = "method_id"

    def get_queryset(self):
        return VendorSelector.payment_methods(
            user=self.request.user,
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


class SetPrimaryPaymentMethodAPIView(APIView):
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
            vendor__user=request.user,
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