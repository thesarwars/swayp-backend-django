"""Onboarding summary aggregates (E5-S6).

Every figure is derived from the same selectors the bills and vendors screens
use, so the summary cannot drift from what those screens show.
"""

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.banking.models import (
    BankConnection,
    BankConnectionStatus,
    BillDetectionCandidate,
)
from apps.bills.selectors.bill_occurrence_selector import BillOccurrenceSelector
from apps.common.enums import VendorPaymentMethodType, VendorStatus
from apps.vendors.models import Vendor


class OnboardingSelector:

    def summary(self, user, today=None):
        today = today or timezone.localdate()

        return {
            "connection": self.connection_meta(user),
            "detection": self.detection_counts(user),
            "bills": self.bill_totals(user, today),
            "rail_readiness": self.rail_readiness(user),
        }

    def connection_meta(self, user):
        connection = (
            BankConnection.objects.filter(
                user=user, status=BankConnectionStatus.ACTIVE
            )
            .prefetch_related("accounts")
            .order_by("-created_at")
            .first()
        )

        if connection is None:
            return None

        account = connection.accounts.filter(
            is_default_funding_source=True
        ).first() or connection.accounts.first()

        return {
            "connection_id": connection.id,
            "institution_name": connection.institution_name,
            "institution_logo": connection.institution_logo,
            "status": connection.status,
            "connected_at": connection.consented_at,
            "account_count": connection.accounts.count(),
            "funding_account": (
                {
                    "account_id": account.id,
                    "name": account.name,
                    "mask": account.mask,
                    "display": account.masked_name,
                }
                if account
                else None
            ),
        }

    def detection_counts(self, user):
        aggregates = BillDetectionCandidate.objects.filter(
            scan__connection__user=user
        ).aggregate(
            detected=Count("id"),
            imported=Count("id", filter=Q(imported_bill__isnull=False)),
        )

        detected = aggregates["detected"] or 0
        imported = aggregates["imported"] or 0

        return {
            "detected": detected,
            "imported": imported,
            "pending": detected - imported,
        }

    def bill_totals(self, user, today):
        # Reuses the E4-S2 summary so these numbers reconcile by construction.
        summary = BillOccurrenceSelector().get_summary(user, today=today)

        return {
            "total_due_this_month": summary["total_due_this_month"],
            "overdue_count": summary["overdue_count"],
            "due_count": summary["due_count"],
            "upcoming_count": summary["upcoming_count"],
        }

    def rail_readiness(self, user):
        """How ready each vendor is to actually be paid.

        A vendor with no payment method cannot be paid at all, so it is
        reported as needing details rather than being silently counted.
        """
        vendors = Vendor.objects.filter(
            user=user, status=VendorStatus.ACTIVE
        ).annotate(
            network=Count(
                "payment_methods",
                filter=Q(
                    payment_methods__method_type=(
                        VendorPaymentMethodType.NETWORK
                    )
                ),
            ),
            ach=Count(
                "payment_methods",
                filter=Q(
                    payment_methods__method_type=VendorPaymentMethodType.ACH
                ),
            ),
            check=Count(
                "payment_methods",
                filter=Q(
                    payment_methods__method_type=VendorPaymentMethodType.CHECK
                ),
            ),
        )

        network_matched = ach_captured = check_ready = needs_details = 0

        for vendor in vendors:
            if vendor.network:
                network_matched += 1
            elif vendor.ach:
                ach_captured += 1
            elif vendor.check:
                check_ready += 1
            else:
                needs_details += 1

        return {
            "total_vendors": len(vendors),
            "network_matched": network_matched,
            "ach_captured": ach_captured,
            "check_ready": check_ready,
            "needs_details": needs_details,
        }
