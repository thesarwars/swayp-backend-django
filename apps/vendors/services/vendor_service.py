from django.db import transaction
from apps.common.enums import ProviderStatus
from apps.vendors.models import Vendor, VendorPaymentMethod


class VendorService:

    @staticmethod
    @transaction.atomic
    def create_vendor(*, user, validated_data):

        payment_method_data = validated_data.pop("payment_method")

        vendor = Vendor.objects.create(
            user=user,
            **validated_data,
        )

        VendorPaymentMethod.objects.create(
            vendor=vendor,
            is_primary=True,
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

        vendor.status = ProviderStatus.DELETED
        vendor.save(update_fields=["status"])


from django.db import transaction


class VendorPaymentMethodService:

    @staticmethod
    @transaction.atomic
    def create(*,vendor,validated_data,):

        if validated_data.get("is_primary"):

            VendorPaymentMethod.objects.filter(
                vendor=vendor
            ).update(
                is_primary=False
            )

        return VendorPaymentMethod.objects.create(vendor=vendor,**validated_data,)
    
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

        payment_method.delete()

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