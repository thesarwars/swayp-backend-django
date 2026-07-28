from django.db import models

from apps.common.enums import PaymentStageStatus
from apps.common.models import BaseModel


class PaymentStageName(models.TextChoices):
    AUTHORIZED = "AUTHORIZED", "Authorized"
    DEBITING = "DEBITING", "Debiting"
    ROUTING = "ROUTING", "Routing"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"


#: Display order for the processing drawer.
STAGE_ORDER = {
    PaymentStageName.AUTHORIZED: 1,
    PaymentStageName.DEBITING: 2,
    PaymentStageName.ROUTING: 3,
    PaymentStageName.COMPLETED: 4,
    PaymentStageName.FAILED: 5,
}


class PaymentStage(BaseModel):
    """One step of execution — drives the live processing drawer (E6-S1).

    Supersedes the payment_tracking app, which only ever held a single status
    and so could not show a checklist.
    """

    payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.CASCADE,
        related_name="stages",
    )

    stage = models.CharField(
        max_length=20,
        choices=PaymentStageName.choices,
    )

    status = models.CharField(
        max_length=20,
        choices=PaymentStageStatus.choices,
        default=PaymentStageStatus.PENDING,
    )

    order = models.PositiveSmallIntegerField(default=0)

    detail = models.CharField(max_length=255, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "payment_stages"
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "stage"],
                name="uniq_stage_per_payment",
            ),
        ]
        indexes = [models.Index(fields=["payment", "order"])]

    def __str__(self):
        return f"{self.stage}:{self.status}"
