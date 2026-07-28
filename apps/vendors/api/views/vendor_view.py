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


class VendorListCreateAPIView(ListCreateAPIView):

    permission_classes = [IsAuthenticated]

    def get_queryset(self):

        return VendorSelector.list(
            self.request.user,
            filters=self.request.query_params,
        )

    def get_serializer_class(self):

        if self.request.method == "POST":
            return VendorCreateSerializer

        return VendorListSerializer

    def create(self, request, *args, **kwargs):

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vendor = VendorService.create_vendor(user=request.user,validated_data=serializer.validated_data,)

        response = VendorDetailSerializer(vendor)

        return Response(
            response.data,
            status=status.HTTP_201_CREATED,
        )
    
class VendorDetailAPIView(RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = "vendor_id"

    def get_object(self):
        return VendorSelector.detail(
            user=self.request.user,
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

class VendorSummaryAPIView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        data = VendorSelector.summary(
            request.user,
            filters=request.query_params,
        )
        serializer = VendorSummarySerializer(instance=data)

        return Response(serializer.data)