from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from apps.common.enums import ProviderStatus
from apps.vendors.models import (
    Vendor,
    VendorPaymentMethod,
)



class VendorSelector:

    @staticmethod
    def list(user):
        return (
            Vendor.objects.filter(
                user=user,
                status=ProviderStatus.ACTIVE,
            )
            .select_related("category")
            .prefetch_related(
                Prefetch(
                    "payment_methods",
                    queryset=VendorPaymentMethod.objects.filter(
                        is_primary=True
                    ),
                )
            )
        )

    @staticmethod
    def detail(user, vendor_id):
        return get_object_or_404(
            Vendor.objects.select_related("category").prefetch_related(
                "payment_methods"
            ),
            id=vendor_id,
            user=user,
            status=ProviderStatus.ACTIVE,
        )

    @staticmethod
    def summary(user):
        vendors = Vendor.objects.filter(
            user=user,
            status=ProviderStatus.ACTIVE,
        )

        return {
            "total": vendors.count(),
            "network": vendors.filter(
                payment_methods__method_type="NETWORK"
            ).distinct().count(),
            "ach": vendors.filter(
                payment_methods__method_type="ACH"
            ).distinct().count(),
            "check": vendors.filter(
                payment_methods__method_type="CHECK"
            ).distinct().count(),
            "check_total": 0,
        }

    @staticmethod
    def payment_methods(user, vendor_id):
        return (
            VendorPaymentMethod.objects.filter(
                vendor__id=vendor_id,
                vendor__user=user,
                vendor__status=ProviderStatus.ACTIVE,
            )
            .order_by("-is_primary", "method_type")
        )