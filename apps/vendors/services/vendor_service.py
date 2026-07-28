from django.db import transaction
from apps.common.enums import VendorStatus
from apps.vendors.models import Vendor, VendorPaymentMethod


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

        vendor.status = VendorStatus.DELETED
        vendor.save(update_fields=["status"])


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