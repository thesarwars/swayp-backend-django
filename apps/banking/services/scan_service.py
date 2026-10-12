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

from apps.common.exceptions import NotFoundException

from apps.banking.models import (
    BankConnection,
    BankConnectionStatus,
    BillDetectionCandidate,
    TransactionScan,
)
from apps.banking.services.recurring_detector import detect
from apps.bill_categories.models import BillCategory
from apps.common.enums import ScanErrorCode, ScanStatus
from integrations.bank_data.base import (
    BankDataNotReady,
    BankReauthRequired,
)
from integrations.factory import get_bank_data_provider

logger = logging.getLogger(__name__)

#: BRD §3.1. Screens 836:8984/9052 say 24 months — design bug, PRD §11.
MAX_MONTHS_HISTORY = 24

#: What the user reads for an unexpected failure (BANK-9). Fixed text: the
#: real cause goes to the log, not to the screen.
SCAN_FAILED_MESSAGE = (
    "We couldn't finish reading your bank history. Try scanning again; if "
    "it keeps failing, contact support."
)

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
            raise NotFoundException("Scan not found.")

        return scan

    def run(self, scan):
        """Fetch history, detect patterns, write candidates.

        Deliberately NOT wrapped in a single transaction. The progress screen
        polls this scan row while the work runs, and inside one atomic block
        every intermediate save stays invisible until commit — the poller
        would see 0 and then jump straight to the final count.

        Each candidate write is individually atomic and idempotent
        (get_or_create against the unique constraint), so a partial run leaves
        valid rows and a retry simply completes it.
        """
        try:
            transactions = self.provider.get_transactions(
                access_token=scan.connection.access_token,
                months=scan.months_history,
            )

            scan.transactions_scanned = len(transactions)
            scan.save(update_fields=["transactions_scanned", "updated_at"])

            detected = detect(transactions)

            seen = 0
            for row in detected:
                with transaction.atomic():
                    BillDetectionCandidate.objects.get_or_create(
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

                # Counts every candidate the scan has, not just the ones this
                # pass inserted — otherwise re-running a scan finds everything
                # already present and reports 0 detected.
                seen += 1
                # Written as we go so the progress screen sees the count climb
                # rather than jumping at the end.
                scan.detected_count = seen
                scan.save(update_fields=["detected_count", "updated_at"])

            scan.detected_count = BillDetectionCandidate.objects.filter(
                scan=scan
            ).count()
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

        except BankDataNotReady as exc:
            # Not a failure. Plaid pulls an item's history asynchronously
            # after it is linked, so the first scan of a new connection —
            # which is every user's onboarding — routinely asks before the
            # data has landed. Left RUNNING, the progress screen keeps waiting
            # and a retry finishes the job; marked FAILED, every single first
            # connect would end on an error screen with nothing wrong.
            logger.info(
                "scan %s is waiting on the provider (%s)", scan.pk, exc
            )

            scan.error_message = ""
            scan.error_code = ""
            scan.save(
                update_fields=["error_message", "error_code", "updated_at"]
            )

            return scan

        except BankReauthRequired as exc:
            # The connection is what broke, not the scan, and only the user
            # can fix it. Recording it on the scan alone would leave the
            # connection looking healthy and every later scan failing the
            # same way.
            logger.info("scan %s needs reauth (%s)", scan.pk, exc)

            scan.connection.status = BankConnectionStatus.ERROR
            scan.connection.save(update_fields=["status", "updated_at"])

            scan.status = ScanStatus.FAILED
            scan.error_code = ScanErrorCode.REAUTH_REQUIRED
            scan.error_message = (
                "Your bank needs you to sign in again before Swayp can read "
                "this account."
            )
            scan.completed_at = timezone.now()
            scan.save(
                update_fields=[
                    "status",
                    "error_code",
                    "error_message",
                    "completed_at",
                    "updated_at",
                ]
            )

            return scan

        except Exception as exc:
            logger.exception("scan %s failed", scan.pk)

            scan.status = ScanStatus.FAILED
            scan.error_code = ScanErrorCode.SCAN_FAILED
            # Never str(exc): that put provider error bodies and internal
            # messages on the user's screen. The detail is in the log above.
            scan.error_message = SCAN_FAILED_MESSAGE
            scan.completed_at = timezone.now()
            scan.save(
                update_fields=[
                    "status",
                    "error_code",
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

            # ``category_names`` is a preference order, not a set:
            # ("Commercial Rent", "Rent"), ("Telecom", "Utilities"),
            # ("SaaS", "Software") each name the specific category first.
            # ``.first()`` applied the model's own ordering instead
            # (display_order, name), so the preference was discarded and the
            # answer was whichever category happened to sort earliest — a
            # WeWork charge landed in "Rent" while "Commercial Rent" existed.
            # One query, then resolved in the declared order.
            matches = {
                category.name: category
                for category in BillCategory.objects.filter(
                    name__in=category_names, is_active=True
                )
            }

            for name in category_names:
                if name in matches:
                    return matches[name]

        return None

    def history_span_days(self, scan):
        """Roughly how much history the scan covered."""
        return scan.months_history * 30

    def is_thin_history(self, scan):
        return self.history_span_days(scan) < THIN_HISTORY_DAYS
