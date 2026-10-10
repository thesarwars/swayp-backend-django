from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.vendors.api.serializers.vendor import (
    VendorCreateSerializer,
    VendorListSerializer,
    VendorDetailSerializer,
    VendorUpdateSerializer,
    VendorSummarySerializer,
)

from apps.vendors.selectors.vendor_selector import (
    VendorSelector,
)
from rest_framework.views import APIView
from apps.vendors.services.vendor_service import (
    VendorService,
)
from apps.teams.access import AccountScopedMixin
from apps.vendors.models import Vendor


@extend_schema_view(
    post=extend_schema(
        summary="Create a vendor",
        description=(
            "201 with the full vendor (the detail shape), including id and "
            "payment_methods[].account_ref."
        ),
        request=VendorCreateSerializer,
        responses={201: VendorDetailSerializer},
    ),
)
class VendorListCreateAPIView(AccountScopedMixin, ListCreateAPIView):

    permission_classes = [IsAuthenticated]

    def get_queryset(self):

        return VendorSelector.list(
            self.account(self.request),
            filters=self.request.query_params,
        )

    def get_serializer_class(self):

        if self.request.method == "POST":
            return VendorCreateSerializer

        return VendorListSerializer

    def create(self, request, *args, **kwargs):

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vendor = VendorService.create_vendor(user=self.account(request),validated_data=serializer.validated_data,)

        response = VendorDetailSerializer(vendor)

        return Response(
            response.data,
            status=status.HTTP_201_CREATED,
        )
    
class VendorDetailAPIView(AccountScopedMixin, RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = "vendor_id"

    def get_object(self):
        return VendorSelector.detail(
            user=self.account(self.request),
            vendor_id=self.kwargs["vendor_id"],
        )

    def get_serializer_class(self):
        if self.request.method in ["PUT", "PATCH"]:
            return VendorUpdateSerializer
        return VendorDetailSerializer

    def perform_update(self, serializer):
        VendorService.update_vendor(
            vendor=serializer.instance,
            validated_data=serializer.validated_data,
        )

    def perform_destroy(self, instance):
        VendorService.soft_delete(instance)

class VendorSummaryAPIView(AccountScopedMixin, APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        data = VendorSelector.summary(
            self.account(request),
            filters=request.query_params,
        )
        serializer = VendorSummarySerializer(instance=data)

        return Response(serializer.data)

@extend_schema(
    tags=["Vendors"],
    summary="Restore a deleted vendor",
    description=(
        "Undoes a delete. The vendor's bills that were deleted with it come "
        "back on REMIND (their autopay authorization was revoked; turning "
        "autopay back on needs fresh consent), and their upcoming "
        "occurrences are regenerated. Bills deleted separately stay deleted. "
        "400 if the vendor is not deleted."
    ),
    request=None,
    responses={200: VendorDetailSerializer},
)
class VendorRestoreAPIView(AccountScopedMixin, APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request, vendor_id):
        vendor = get_object_or_404(
            Vendor, id=vendor_id, user=self.account(request)
        )

        VendorService.restore(vendor)

        return Response(VendorDetailSerializer(vendor).data)
