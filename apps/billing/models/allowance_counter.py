from django.db import models

from apps.common.models import BaseModel


class AllowanceKind(models.TextChoices):
    # Metered: consumed over a cycle and resets.
    CHECKS = "CHECKS", "Checks"
    # Capacity: a standing ceiling, checked at add-time, never resets.
    SEATS = "SEATS", "Seats"
    BANKS = "BANKS", "Banks"


#: Metered kinds reset each cycle; capacity kinds do not. Keeping the split
#: explicit stops a seat count being silently zeroed at renewal.
METERED_KINDS = (AllowanceKind.CHECKS,)
CAPACITY_KINDS = (AllowanceKind.SEATS, AllowanceKind.BANKS)


class AllowanceCounter(BaseModel):
    """Usage against a plan allowance, per subscription per cycle (E9-S2)."""

    subscription = models.ForeignKey(
        "billing.Subscription",
        on_delete=models.CASCADE,
        related_name="counters",
    )

    kind = models.CharField(max_length=20, choices=AllowanceKind.choices)

    # For capacity kinds this is the subscription's period_start and simply
    # never rolls; for metered kinds it is what makes the counter reset.
    period_start = models.DateField()

    used = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "allowance_counters"
        ordering = ["-period_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "kind", "period_start"],
                name="uniq_counter",
            ),
        ]
        indexes = [
            models.Index(fields=["subscription", "kind"]),
        ]

    def __str__(self):
        return f"{self.kind}={self.used} @ {self.period_start}"
