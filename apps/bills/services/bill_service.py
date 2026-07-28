from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.bill_categories.models import BillCategory
from apps.bills.models.bill import Bill
from apps.bills.selectors.bill_selector import BillSelector
from apps.bills.serializers.bill_review_serializer import build_review
from apps.bills.services.bill_occurrence_service import BillOccurrenceService
from apps.bills.services.consent_service import ConsentService
from apps.common.enums import AutopayMode
from apps.vendors.models import Vendor, VendorPaymentMethod


class BillService:

    def __init__(self):
        self.selector = BillSelector()
        self.occurrence_service = BillOccurrenceService()
        self.consent_service = ConsentService()

    @transaction.atomic
    def create_bill(self, *, user, validated_data, meta=None):
        consent = validated_data.get("autopay_consent")

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

        # Consent before anything else observable: if AUTO is requested and the
        # authorization cannot be recorded, the whole create rolls back rather
        # than leaving a bill set to auto-pay with nothing backing it.
        if bill.autopay_mode == AutopayMode.AUTO:
            self.consent_service.capture(
                bill=bill,
                consent=consent,
                meta=meta,
            )

        # Seed the first occurrences now rather than waiting for the nightly
        # beat, so the bill has rows the moment the wizard closes.
        self.occurrence_service.generate_occurrences(bill)

        return bill

    def review(self, bill):
        """The wizard's closing summary for ``bill`` (E4-S3)."""
        next_occurrence = (
            self.occurrence_service.open_occurrences(bill)
            .order_by("due_date")
            .first()
        )

        return build_review(
            bill,
            next_due_date=next_occurrence.due_date if next_occurrence else None,
            autopay_authorized=self.consent_service.has_active_authorization(
                bill
            ),
        )

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

    #: Editing any of these changes the recurrence, so the unsettled part of
    #: the schedule has to be rebuilt rather than left disagreeing with it.
    SCHEDULE_FIELDS = ("frequency", "anchor_date")

    @transaction.atomic
    def update_bill(self, bill_id, user, validated_data, meta=None):
        bill = self.get_bill(
            bill_id=bill_id,
            user=user,
        )

        consent = validated_data.get("autopay_consent")

        autopay_changed = (
            "autopay_mode" in validated_data
            and validated_data["autopay_mode"] != bill.autopay_mode
        )

        schedule_changed = any(
            field in validated_data
            and validated_data[field] != getattr(bill, field)
            for field in self.SCHEDULE_FIELDS
        )

        amount_changed = (
            "amount" in validated_data
            and validated_data["amount"] != bill.amount
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

        # Switching to AUTO captures a fresh authorization; switching away
        # revokes the live one (E4-S5).
        if autopay_changed:
            self.consent_service.sync_for_mode(
                bill=bill,
                autopay_mode=bill.autopay_mode,
                consent=consent,
                meta=meta,
            )

        if schedule_changed:
            self.occurrence_service.rebuild_schedule(bill)
        elif amount_changed:
            self.occurrence_service.reprice_open_occurrences(bill)

        return bill

    @transaction.atomic
    def delete_bill(self, bill_id, user):
        """Soft delete (E4-S5).

        Future unpaid occurrences go; anything settled stays, along with the
        bill row itself, because the payment history references it.
        """
        bill = self.get_bill(bill_id=bill_id, user=user)

        self.occurrence_service.drop_open_occurrences(bill)

        # A live debit mandate must not outlive the bill it authorized.
        self.consent_service.revoke(bill=bill)

        bill.deleted_at = timezone.now()
        bill.save(update_fields=["deleted_at", "updated_at"])

        return True
