"""Recent vendor activity for the account (VEND-5)."""

from apps.common.mixins import EnvelopeResponseMixin
from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from apps.teams.access import AccountScopedMixin
from apps.vendors.api.serializers.activity import VendorActivitySerializer
from apps.vendors.models import VendorActivity


@extend_schema(
    tags=["Vendors"],
    summary="Recent vendor activity",
    description=(
        "Newest first: vendors added, updated, removed and restored, and "
        "payment methods added, changed or removed, with who did it. "
        "Paginated like the vendor list ({items, pagination})."
    ),
)
class VendorActivityListAPIView(EnvelopeResponseMixin, AccountScopedMixin, ListAPIView):

    # {success, message, data} like every module (web C1).

    permission_classes = [IsAuthenticated]
    serializer_class = VendorActivitySerializer

    def get_queryset(self):
        return (
            VendorActivity.objects.filter(account=self.account(self.request))
            .select_related("actor")
            .order_by("-created_at", "-id")
        )
