from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.common.enums import PaymentStatus, VendorStatus
from apps.vendors.models import Vendor, VendorPaymentMethod

#: A payment in one of these states still expects to pay this vendor.
_LIVE_PAYMENT_STATUSES = (
    PaymentStatus.SCHEDULED,
    PaymentStatus.PENDING,
    PaymentStatus.PROCESSING,
)


class VendorService:

    @staticmethod
    @transaction.atomic
    def create_vendor(*, user, validated_data):

        payment_method_data = dict(validated_data.pop("payment_method"))

        vendor = Vendor.objects.create(
            user=user,
            **validated_data,
        )

        # A vendor's first method is its primary one. setdefault rather than a
        # keyword: passing is_primary here while the client also sent it in the
        # payload raised TypeError and 500'd the whole create.
        payment_method_data.setdefault("is_primary", True)

        VendorPaymentMethod.objects.create(
            vendor=vendor,
            **payment_method_data,
        )

        return vendor
 
    @staticmethod
    @transaction.atomic
    def update_vendor(*, vendor, validated_data):

        for field, value in validated_data.items():
            setattr(vendor, field, value)

        vendor.save()

        return vendor

    @staticmethod
    @transaction.atomic
    def soft_delete(vendor):
        # Don't strand money already headed to this vendor.
        from apps.payments.models import Payment

        live = Payment.objects.filter(
            vendor=vendor,
            status__in=_LIVE_PAYMENT_STATUSES,
        ).count()

        if live:
            raise ValidationError(
                {
                    "vendor": (
                        f"Cannot delete while {live} payment(s) are scheduled "
                        "or in flight. Cancel or wait for them to settle first."
                    )
                }
            )

        # The vendor's bills go with it (VEND-11). Marking only the vendor
        # left its bills live: the nightly job kept creating occurrences,
        # reminders kept going out, and autopay kept paying a vendor the user
        # had deleted. Each bill is soft-deleted the way a bill delete does it
        # (open occurrences dropped, autopay authorization revoked, paid
        # history kept), stamped with the vendor's own deletion time.
        from apps.bills.services.bill_service import BillService

        now = timezone.now()
        bills = BillService()

        for bill in vendor.bills.filter(deleted_at__isnull=True):
            bills.occurrence_service.drop_open_occurrences(bill)
            bills.consent_service.revoke(bill=bill)
            bill.deleted_at = now
            bill.save(update_fields=["deleted_at", "updated_at"])

        vendor.status = VendorStatus.DELETED
        vendor.deleted_at = now
        vendor.save(update_fields=["status", "deleted_at", "updated_at"])

    @staticmethod
    @transaction.atomic
    def restore(vendor):
        """Undo a delete, bringing back the bills that went with it (VEND-11).

        Only bills deleted at the vendor's deletion time come back; one the
        user deleted earlier stays deleted. Restored bills come back on
        REMIND: their autopay authorization was revoked, and paying
        automatically again needs fresh consent.
        """
        from apps.bills.services.bill_service import BillService
        from apps.common.enums import AutopayMode

        if vendor.status != VendorStatus.DELETED:
            raise ValidationError({"vendor": "This vendor is not deleted."})

        bills = BillService()

        if vendor.deleted_at is not None:
            for bill in vendor.bills.filter(deleted_at=vendor.deleted_at):
                bill.deleted_at = None
                bill.autopay_mode = AutopayMode.REMIND
                bill.save(
                    update_fields=["deleted_at", "autopay_mode", "updated_at"]
                )
                bills.occurrence_service.generate_occurrences(bill)

        vendor.status = VendorStatus.ACTIVE
        vendor.deleted_at = None
        vendor.save(update_fields=["status", "deleted_at", "updated_at"])

        return vendor


class VendorPaymentMethodService:

    @staticmethod
    @transaction.atomic
    def create(*, vendor, validated_data):

        if validated_data.get("is_primary"):

            VendorPaymentMethod.objects.filter(
                vendor=vendor
            ).update(
                is_primary=False
            )

        payment_method = VendorPaymentMethod.objects.create(vendor=vendor,**validated_data)

        return payment_method

    @staticmethod
    @transaction.atomic
    def update(*, payment_method, validated_data):

        if validated_data.get("is_primary"):

            VendorPaymentMethod.objects.filter(
                vendor=payment_method.vendor
            ).exclude(
                id=payment_method.id
            ).update(
                is_primary=False
            )

        for field, value in validated_data.items():
            setattr(payment_method, field, value)

        payment_method.save()

        return payment_method

    @staticmethod
    @transaction.atomic
    def delete(payment_method):
        """Delete a method, promoting a replacement if it was the primary.

        Without this a vendor keeps its remaining methods but ends up with no
        primary at all, so its rail chip goes blank and nothing knows how to
        pay it.
        """
        was_primary = payment_method.is_primary
        vendor = payment_method.vendor

        payment_method.delete()

        if not was_primary:
            return

        replacement = (
            VendorPaymentMethod.objects.filter(vendor=vendor)
            .order_by("created_at")
            .first()
        )

        if replacement:
            replacement.is_primary = True
            replacement.save(update_fields=["is_primary"])

    @staticmethod
    @transaction.atomic
    def set_primary(payment_method):

        VendorPaymentMethod.objects.filter(
            vendor=payment_method.vendor
        ).update(
            is_primary=False
        )

        payment_method.is_primary = True
        payment_method.save(update_fields=["is_primary"])

        return payment_method