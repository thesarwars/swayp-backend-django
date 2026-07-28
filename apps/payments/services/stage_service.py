"""PaymentStage bookkeeping (E6-S1 / E6-S4 / E6-S7).

The stage rows are what the processing drawer renders, so they are written as
execution progresses rather than all at once at the end.
"""

from django.utils import timezone

from apps.common.enums import PaymentStageStatus
from apps.payments.models import STAGE_ORDER, PaymentStage, PaymentStageName

#: The happy path, in display order.
PIPELINE = (
    PaymentStageName.AUTHORIZED,
    PaymentStageName.DEBITING,
    PaymentStageName.ROUTING,
    PaymentStageName.COMPLETED,
)


class StageService:

    def seed(self, payment):
        """Create the checklist as PENDING so the drawer has rows to show."""
        for stage in PIPELINE:
            PaymentStage.objects.get_or_create(
                payment=payment,
                stage=stage,
                defaults={"order": STAGE_ORDER[stage]},
            )

        return payment.stages.all()

    def mark(self, payment, stage, status, detail=""):
        """Move one stage, stamping the timestamps the drawer displays."""
        now = timezone.now()

        row, _ = PaymentStage.objects.get_or_create(
            payment=payment,
            stage=stage,
            defaults={"order": STAGE_ORDER.get(stage, 99)},
        )

        row.status = status
        row.detail = detail or row.detail

        if status == PaymentStageStatus.RUNNING and row.started_at is None:
            row.started_at = now

        if status in (PaymentStageStatus.DONE, PaymentStageStatus.FAILED):
            row.started_at = row.started_at or now
            row.finished_at = now

        row.save(
            update_fields=[
                "status",
                "detail",
                "started_at",
                "finished_at",
                "updated_at",
            ]
        )

        return row

    def fail(self, payment, detail=""):
        """Mark the first unfinished stage failed and add a FAILED row.

        Leaves completed stages alone — the drawer should still show how far
        the payment got before it broke.
        """
        pending = (
            payment.stages.exclude(status=PaymentStageStatus.DONE)
            .order_by("order")
            .first()
        )

        if pending is not None:
            self.mark(
                payment, pending.stage, PaymentStageStatus.FAILED, detail
            )

        return self.mark(
            payment, PaymentStageName.FAILED, PaymentStageStatus.FAILED, detail
        )

    def checklist(self, payment):
        """Ordered stages for the status endpoint."""
        return payment.stages.order_by("order")
