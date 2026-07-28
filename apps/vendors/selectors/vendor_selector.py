from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from apps.common.enums import VendorPaymentMethodType, VendorStatus
from apps.vendors.models import (
    Vendor,
    VendorPaymentMethod,
)

_VALID_STATUSES = {choice.value for choice in VendorStatus}
_VALID_RAILS = {choice.value for choice in VendorPaymentMethodType}


class VendorSelector:

    @staticmethod
    def list(user, filters=None):
        """Vendor rows for the list screen (E3-S2).

        Supports ``search`` (name contains), ``category``, ``rail`` (the
        vendor's primary payment method) and ``status``. Filtering lives here
        rather than in the view so list and summary share one definition.
        """
        filters = filters or {}

        status = (filters.get("status") or "").strip().upper()

        if status not in _VALID_STATUSES:
            status = VendorStatus.ACTIVE

        queryset = Vendor.objects.filter(user=user, status=status)

        search = (filters.get("search") or "").strip()
        if search:
            queryset = queryset.filter(name__icontains=search)

        category = (filters.get("category") or "").strip()
        if category:
            queryset = queryset.filter(category_id=category)

        rail = (filters.get("rail") or "").strip().upper()
        if rail in _VALID_RAILS:
            # Both conditions must hold on the *same* payment method, so they
            # stay inside one filter() call.
            queryset = queryset.filter(
                payment_methods__is_primary=True,
                payment_methods__method_type=rail,
            )

        return (
            queryset.select_related("category")
            .prefetch_related(
                Prefetch(
                    "payment_methods",
                    queryset=VendorPaymentMethod.objects.filter(
                        is_primary=True
                    ),
                )
            )
            .distinct()
        )

    @staticmethod
    def detail(user, vendor_id):
        return get_object_or_404(
            Vendor.objects.select_related("category").prefetch_related(
                "payment_methods"
            ),
            id=vendor_id,
            user=user,
            status=VendorStatus.ACTIVE,
        )

    @staticmethod
    def summary(user, filters=None):
        """Counts over the same rows the list returns under ``filters``."""
        vendors = VendorSelector.list(user, filters)

        return {
            "total": vendors.count(),
            "network": vendors.filter(
                payment_methods__method_type=VendorPaymentMethodType.NETWORK
            ).distinct().count(),
            "ach": vendors.filter(
                payment_methods__method_type=VendorPaymentMethodType.ACH
            ).distinct().count(),
            "check": vendors.filter(
                payment_methods__method_type=VendorPaymentMethodType.CHECK
            ).distinct().count(),
            # TODO(E3-S2): "check $ total" needs bill/payment amounts, which
            # arrive with E6. Reported as 0 rather than guessed at.
            "check_total": 0,
        }

    @staticmethod
    def payment_methods(user, vendor_id):
        return (
            VendorPaymentMethod.objects.filter(
                vendor__id=vendor_id,
                vendor__user=user,
                vendor__status=VendorStatus.ACTIVE,
            )
            .order_by("-is_primary", "method_type")
        )
