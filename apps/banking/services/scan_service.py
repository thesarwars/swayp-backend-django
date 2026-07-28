"""Transaction scan orchestration (E5-S4).

Pulls history through the provider interface and hands it to the deterministic
detector. Progress is written to the scan row as it goes, so the onboarding
screen can poll a single endpoint rather than holding a connection open.

Transactions are never persisted — Swayp only keeps the patterns it derives.
"""

import logging

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.banking.models import (
    BankConnection,
    BillDetectionCandidate,
    TransactionScan,
)
from apps.banking.services.recurring_detector import detect
from apps.bill_categories.models import BillCategory
from apps.common.enums import ScanStatus
from integrations.factory import get_bank_data_provider

logger = logging.getLogger(__name__)

#: BRD §3.1. Screens 836:8984/9052 say 24 months — design bug, PRD §11.
MAX_MONTHS_HISTORY = 12

#: Below this, a "no recurring bills" result means "not enough history",
#: not "you have none". Surfaced so the UI can say so (thin-history AC).
THIN_HISTORY_DAYS = 180

#: Keyword -> category name, applied to the normalised vendor name.
_CATEGORY_HINTS = (
    (("wework", "regus", "office", "rent", "landlord", "properties"),
     ("Commercial Rent", "Rent")),
    (("verizon", "at t", "att", "tmobile", "comcast", "spectrum"),
     ("Telecom", "Utilities")),
    (("con edison", "edison", "national grid", "pg e", "water", "gas",
      "electric"), ("Utilities",)),
    (("amazon web services", "aws", "google cloud", "azure", "github",
      "slack", "notion", "figma", "atlassian"), ("SaaS", "Software")),
    (("insurance", "geico", "allstate", "statefarm"), ("Insurance",)),
)


class ScanService:

    def __init__(self):
        self.provider = get_bank_data_provider()

    def start(self, *, user, connection_id, months=MAX_MONTHS_HISTORY):
        """Create a RUNNING scan and queue the work."""
        connection = BankConnection.objects.filter(
            id=connection_id, user=user
        ).first()

        if connection is None:
            raise ValidationError({"connection": "Connection not found."})

        months = max(1, min(int(months or MAX_MONTHS_HISTORY),
                            MAX_MONTHS_HISTORY))

        scan = TransactionScan.objects.create(
            connection=connection,
            months_history=months,
            status=ScanStatus.RUNNING,
        )

        from apps.banking.tasks import sync_transactions

        transaction.on_commit(
            lambda: sync_transactions.delay(scan_id=str(scan.id))
        )

        return scan

    def get_scan(self, *, user, scan_id):
        scan = (
            TransactionScan.objects.filter(
                id=scan_id, connection__user=user
            )
            .select_related("connection")
            .first()
        )

        if scan is None:
            raise ValidationError({"scan": "Scan not found."})

        return scan

    @transaction.atomic
    def run(self, scan):
        """Fetch history, detect patterns, write candidates."""
        try:
            transactions = self.provider.get_transactions(
                access_token=scan.connection.access_token,
                months=scan.months_history,
            )

            scan.transactions_scanned = len(transactions)
            scan.save(update_fields=["transactions_scanned", "updated_at"])

            detected = detect(transactions)

            created = 0
            for row in detected:
                _, was_created = BillDetectionCandidate.objects.get_or_create(
                    scan=scan,
                    vendor_name=row["vendor_name"],
                    amount=row["amount"],
                    cadence=row["cadence"],
                    defaults={
                        "due_day": row["due_day"],
                        "occurrences": row["occurrences"],
                        "category_guess": self.guess_category(
                            row["vendor_name"]
                        ),
                    },
                )

                if was_created:
                    created += 1
                    # Written per candidate so the progress screen sees the
                    # count climb rather than jumping at the end.
                    scan.detected_count = created
                    scan.save(
                        update_fields=["detected_count", "updated_at"]
                    )

            scan.detected_count = created
            scan.status = ScanStatus.DONE
            scan.completed_at = timezone.now()
            scan.save(
                update_fields=[
                    "detected_count",
                    "status",
                    "completed_at",
                    "updated_at",
                ]
            )

        except Exception as exc:
            logger.exception("scan %s failed", scan.pk)

            scan.status = ScanStatus.FAILED
            scan.error_message = str(exc)[:500]
            scan.completed_at = timezone.now()
            scan.save(
                update_fields=[
                    "status",
                    "error_message",
                    "completed_at",
                    "updated_at",
                ]
            )
            raise

        return scan

    def guess_category(self, vendor_name):
        """Best-effort category, or None. Never invents a category row."""
        from apps.banking.services.recurring_detector import normalize_vendor

        normalized = normalize_vendor(vendor_name)

        for keywords, category_names in _CATEGORY_HINTS:
            if not any(keyword in normalized for keyword in keywords):
                continue

            category = BillCategory.objects.filter(
                name__in=category_names, is_active=True
            ).first()

            if category:
                return category

        return None

    def history_span_days(self, scan):
        """Roughly how much history the scan covered."""
        return scan.months_history * 30

    def is_thin_history(self, scan):
        return self.history_span_days(scan) < THIN_HISTORY_DAYS
