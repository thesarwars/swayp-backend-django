from django.shortcuts import get_object_or_404
from apps.common.mixins import EnvelopeResponseMixin
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
    VendorListQuerySerializer,
    VendorSummarySerializer,
)

from apps.vendors.selectors.vendor_selector import (
    VendorSelector,
)
from rest_framework.views import APIView
from apps.vendors.services.vendor_service import (
    VendorService,
)
from apps.payments.idempotency import IdempotencyMixin
from apps.teams.access import AccountScopedMixin
from apps.vendors.models import (
    Vendor,
    VendorActivityAction,
    record_vendor_activity,
)


@extend_schema_view(
    get=extend_schema(
        summary="Vendors",
        description="{items, pagination}, filtered before paging.",
        parameters=[VendorListQuerySerializer],
    ),
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
class VendorListCreateAPIView(EnvelopeResponseMixin, AccountScopedMixin, IdempotencyMixin, ListCreateAPIView):

    # {success, message, data} like every module (web C1).

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
        # A retry must not save a duplicate payee (API-2).
        return self.run_idempotent(
            request, lambda: self._create(request, *args, **kwargs)
        )

    def _create(self, request, *args, **kwargs):

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vendor = VendorService.create_vendor(user=self.account(request),validated_data=serializer.validated_data,)
        record_vendor_activity(
            vendor=vendor, action=VendorActivityAction.CREATED, actor=request.user
        )

        response = VendorDetailSerializer(vendor)

        return Response(
            response.data,
            status=status.HTTP_201_CREATED,
        )
    
class VendorDetailAPIView(EnvelopeResponseMixin, AccountScopedMixin, RetrieveUpdateDestroyAPIView):

    # {success, message, data} like every module (web C1).
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

    @extend_schema(
        request=VendorUpdateSerializer,
        responses={200: VendorDetailSerializer},
    )
    def patch(self, request, *args, **kwargs):
        return super().patch(request, *args, **kwargs)

    @extend_schema(
        request=VendorUpdateSerializer,
        responses={200: VendorDetailSerializer},
    )
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        """Answer with the full vendor (VEND-9); it used to be the three
        fields that were writable."""
        serializer = self.get_serializer(
            self.get_object(),
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)

        vendor = VendorService.update_vendor(
            vendor=serializer.instance,
            validated_data=serializer.validated_data,
        )
        record_vendor_activity(
            vendor=vendor, action=VendorActivityAction.UPDATED, actor=request.user
        )

        return Response(VendorDetailSerializer(vendor).data)

    def perform_destroy(self, instance):
        VendorService.soft_delete(instance)
        record_vendor_activity(
            vendor=instance,
            action=VendorActivityAction.DELETED,
            actor=self.request.user,
        )

@extend_schema(
    tags=["Vendors"],
    summary="Vendor counts by rail",
    description="Takes the list's filters. Bare body.",
    parameters=[VendorListQuerySerializer],
    responses={200: VendorSummarySerializer},
)
class VendorSummaryAPIView(EnvelopeResponseMixin, AccountScopedMixin, APIView):

    # {success, message, data} like every module (web C1).

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
class VendorRestoreAPIView(EnvelopeResponseMixin, AccountScopedMixin, APIView):

    # {success, message, data} like every module (web C1).

    permission_classes = [IsAuthenticated]

    def post(self, request, vendor_id):
        vendor = get_object_or_404(
            Vendor, id=vendor_id, user=self.account(request)
        )

        VendorService.restore(vendor)
        record_vendor_activity(
            vendor=vendor, action=VendorActivityAction.RESTORED, actor=request.user
        )

        return Response(VendorDetailSerializer(vendor).data)
