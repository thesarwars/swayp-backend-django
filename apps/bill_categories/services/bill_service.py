from apps.bill_categories.selectors.bill_category_selector import (
    BillCategorySelector,
)
from django.db import transaction
from django.shortcuts import get_object_or_404

from apps.bill_categories.models import BillCategory
from apps.bill_categories.models.bill import Bill
from apps.vendors.models import Vendor, VendorPaymentMethod


class BillCategoryService:

    def __init__(self):
        self.selector = BillCategorySelector()

    def get_dashboard_categories(self):
        return self.selector.get_dashboard_categories()



class BillService:

    @staticmethod
    @transaction.atomic
    def create_bill(*, user, validated_data):
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

        return bill