"""Bulk import of detected bills (E5-S5).

Turns candidates into real Vendors and Bills. Idempotent twice over: a
candidate carrying ``imported_bill`` is skipped and reported, and the endpoint
also honours ``Idempotency-Key`` (E1-S7), so a retried request replays rather
than re-imports.
"""

import datetime as dt

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.banking.models import BillDetectionCandidate, TransactionScan
from apps.bill_categories.models import BillCategory
from apps.bills.models.bill import Bill
from apps.bills.services.bill_occurrence_service import BillOccurrenceService
from apps.common.dates import clamp_to_month
from apps.common.enums import (
    AutopayMode,
    BillFrequency,
    BillSource,
    BillType,
    VendorSource,
    VendorStatus,
)
from apps.vendors.models import Vendor

#: Used when a candidate has no category guess and no fallback exists.


class BillImportService:

    def __init__(self):
        self.occurrence_service = BillOccurrenceService()

    def get_scan(self, *, user, scan_id):
        scan = TransactionScan.objects.filter(
            id=scan_id, connection__user=user
        ).select_related("connection").first()

        if scan is None:
            raise ValidationError({"scan": "Scan not found."})

        return scan

    def candidates(self, *, user, scan_id):
        scan = self.get_scan(user=user, scan_id=scan_id)

        return (
            BillDetectionCandidate.objects.filter(scan=scan)
            .select_related("category_guess", "imported_bill")
            .order_by("-occurrences", "vendor_name")
        )

    @transaction.atomic
    def update_candidate(self, *, user, scan_id, candidate_id, data):
        """Correct a detected bill before it is imported (BANK-8).

        Locked, so the imported check below cannot race an import of the
        same row. Refused once imported: the bill exists by then, and
        changing the candidate would only make the two disagree. Edit the
        bill instead.
        """
        scan = self.get_scan(user=user, scan_id=scan_id)

        candidate = (
            BillDetectionCandidate.objects.select_for_update()
            .filter(scan=scan, id=candidate_id)
            .first()
        )

        if candidate is None:
            raise ValidationError({"candidate": "Candidate not found."})

        if candidate.imported_bill_id is not None:
            raise ValidationError(
                {
                    "candidate": (
                        "Already imported. Edit the bill instead."
                    )
                }
            )

        cadence = data.get("cadence", candidate.cadence)
        due_day = data.get("due_day", candidate.due_day)

        # Checked against the cadence the row will have, so changing either
        # one alone cannot leave a weekly bill due on the 15th "weekday".
        if cadence == BillFrequency.WEEKLY and due_day > 7:
            raise ValidationError(
                {
                    "due_day": (
                        "For a weekly bill, due_day is the weekday: "
                        "1 (Monday) to 7 (Sunday)."
                    )
                }
            )

        fields = []

        if "category" in data:
            category = BillCategory.objects.filter(
                id=data["category"], is_active=True
            ).first()

            if category is None:
                raise ValidationError({"category": "Category not found."})

            candidate.category_guess = category
            fields.append("category_guess")

        for name in ("amount", "cadence", "due_day"):
            if name in data:
                setattr(candidate, name, data[name])
                fields.append(name)

        candidate.save(update_fields=fields + ["updated_at"])

        return candidate

    @transaction.atomic
    def import_candidates(self, *, user, scan_id, candidate_ids=None,
                          import_all=False, today=None):
        """Create Vendors + Bills for the selected candidates.

        Returns a report rather than raising on already-imported rows — a
        re-POST is a no-op that says so.
        """
        scan = self.get_scan(user=user, scan_id=scan_id)
        today = today or timezone.localdate()

        queryset = BillDetectionCandidate.objects.filter(scan=scan)

        if not import_all:
            if not candidate_ids:
                raise ValidationError(
                    {
                        "candidate_ids": (
                            "Provide candidate_ids or set all=true."
                        )
                    }
                )
            queryset = queryset.filter(id__in=candidate_ids)

        # Locked like update_candidate, so an edit and an import of the same
        # row run one after the other. of=("self",): category_guess is a
        # nullable join, which Postgres will not lock.
        candidates = list(
            queryset.select_related("category_guess").select_for_update(
                of=("self",)
            )
        )

        if not candidates:
            raise ValidationError(
                {"candidate_ids": "No matching candidates for this scan."}
            )

        imported = []
        skipped = []

        for candidate in candidates:
            if candidate.is_imported:
                skipped.append(
                    {
                        "candidate_id": candidate.id,
                        "vendor_name": candidate.vendor_name,
                        "bill_id": candidate.imported_bill_id,
                        "reason": "already_imported",
                    }
                )
                continue

            bill = self._import_one(user, candidate, today)

            imported.append(
                {
                    "candidate_id": candidate.id,
                    "vendor_name": candidate.vendor_name,
                    "bill_id": bill.id,
                    "vendor_id": bill.vendor_id,
                    "amount": bill.amount,
                    "anchor_date": bill.anchor_date,
                }
            )

        return {
            "scan_id": scan.id,
            "imported_count": len(imported),
            "skipped_count": len(skipped),
            "imported": imported,
            "skipped": skipped,
        }

    def _import_one(self, user, candidate, today):
        category = candidate.category_guess or self._fallback_category()

        vendor = self._find_or_create_vendor(user, candidate, category)

        bill = Bill.objects.create(
            user=user,
            vendor=vendor,
            category=category,
            amount=candidate.amount,
            bill_type=BillType.FIXED,
            frequency=candidate.cadence,
            anchor_date=self.next_anchor_date(
                candidate.cadence, candidate.due_day, today
            ),
            autopay_mode=AutopayMode.REMIND,
            source=BillSource.DETECTED,
            notes=(
                f"Imported from bank scan — {candidate.occurrences} "
                f"occurrences detected."
            ),
        )

        # Seed the schedule so the imported bill has due dates immediately.
        self.occurrence_service.generate_occurrences(bill, today=today)

        candidate.imported_bill = bill
        candidate.save(update_fields=["imported_bill", "updated_at"])

        return bill

    def _find_or_create_vendor(self, user, candidate, category):
        """Reuse an existing vendor by name before creating another."""
        existing = Vendor.objects.filter(
            user=user,
            name__iexact=candidate.vendor_name,
            status=VendorStatus.ACTIVE,
        ).first()

        if existing:
            return existing

        return Vendor.objects.create(
            user=user,
            name=candidate.vendor_name,
            category=category,
            source=VendorSource.IMPORT,
        )

    def next_anchor_date(self, cadence, due_day, today):
        """The next date matching the detected cadence and due day.

        Anchoring forward rather than in the past means an imported bill does
        not immediately read OVERDUE for a cycle the user already paid by hand.
        """
        if cadence == BillFrequency.WEEKLY:
            weekday = max(1, min(int(due_day or 1), 7))
            delta = (weekday - today.isoweekday()) % 7

            return today + dt.timedelta(days=delta or 7)

        day = max(1, min(int(due_day or 1), 31))

        candidate = clamp_to_month(today.year, today.month, day)

        if candidate <= today:
            year = today.year + (1 if today.month == 12 else 0)
            month = 1 if today.month == 12 else today.month + 1
            candidate = clamp_to_month(year, month, day)

        return candidate

    def _fallback_category(self):
        from apps.bill_categories.selectors.default_category import (
            default_category,
        )

        category = default_category()

        if category is None:
            raise ValidationError(
                {
                    "category": (
                        "No bill categories are configured, so detected bills "
                        "cannot be imported."
                    )
                }
            )

        return category
