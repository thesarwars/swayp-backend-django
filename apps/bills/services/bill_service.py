from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.bill_categories.models import BillCategory
from apps.bills.models.bill import Bill
from apps.bills.selectors.bill_selector import BillSelector
from apps.bills.services.bill_occurrence_service import BillOccurrenceService
from apps.vendors.models import Vendor, VendorPaymentMethod


class BillService:

    def __init__(self):
        self.selector = BillSelector()
        self.occurrence_service = BillOccurrenceService()

    @transaction.atomic
    def create_bill(self, *, user, validated_data):
        vendor = get_object_or_404(
            Vendor,
            id=validated_data["vendor"],
            user=user,
        )

        category = get_object_or_404(
            BillCategory,
            id=validated_data["category"],
        )

        payment_method = None
        payment_method_id = validated_data.get("payment_method")

        if payment_method_id:
            payment_method = get_object_or_404(
                VendorPaymentMethod,
                id=payment_method_id,
                vendor=vendor,
            )

        bill = Bill.objects.create(
            user=user,
            vendor=vendor,
            category=category,
            payment_method=payment_method,
            bill_type=validated_data["bill_type"],
            amount=validated_data["amount"],
            frequency=validated_data["frequency"],
            anchor_date=validated_data["anchor_date"],
            autopay_mode=validated_data["autopay_mode"],
            source=validated_data["source"],
            notes=validated_data.get("notes", ""),
        )

        # Seed the first occurrences now rather than waiting for the nightly
        # beat, so the bill has rows the moment the wizard closes.
        self.occurrence_service.generate_occurrences(bill)

        return bill

    def get_user_bills(self, user):
        return self.selector.get_user_bills(user)

    def get_bill(self, bill_id, user):
        bill = self.selector.get_bill(
            bill_id=bill_id,
            user=user,
        )

        if not bill:
            raise ValidationError(
                {"bill": "Bill not found."}
            )

        return bill

    def get_bill_detail(self, bill_id, user):
        bill = self.selector.get_bill_detail(
            bill_id=bill_id,
            user=user,
        )

        if not bill:
            raise ValidationError(
                {
                    "bill": "Bill not found."
                }
            )

        return bill

    def update_bill(self, bill_id, user, validated_data):
        bill = self.get_bill(
            bill_id=bill_id,
            user=user,
        )

        if "category" in validated_data:
            bill.category = get_object_or_404(
                BillCategory,
                id=validated_data["category"],
            )

        if "payment_method" in validated_data:
            payment_method_id = validated_data["payment_method"]

            if payment_method_id is None:
                bill.payment_method = None
            else:
                payment_method = VendorPaymentMethod.objects.filter(
                    id=payment_method_id,
                    vendor=bill.vendor,
                ).first()

                if not payment_method:
                    raise ValidationError(
                        {
                            "payment_method": "Invalid payment method."
                        }
                    )

                bill.payment_method = payment_method

        for field in (
            "bill_type",
            "amount",
            "frequency",
            "anchor_date",
            "autopay_mode",
            "source",
            "notes",
        ):
            if field in validated_data:
                setattr(
                    bill,
                    field,
                    validated_data[field],
                )

        bill.full_clean()
        bill.save()

        return bill

    def delete_bill(self, bill_id, user):
        bill = self.get_bill(bill_id=bill_id, user=user)

        bill.delete()

        return True
