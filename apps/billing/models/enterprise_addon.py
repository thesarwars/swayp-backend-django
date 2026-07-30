from decimal import Decimal

from django.db import models

from apps.common.models import BaseModel


class AddOnKind(models.TextChoices):
    EXTRA_ENTITY = "EXTRA_ENTITY", "Extra entity"
    APPROVAL_WORKFLOW = "APPROVAL_WORKFLOW", "Approval workflow"
    ERP_SYNC = "ERP_SYNC", "ERP sync"
    CUSTOM_SLA = "CUSTOM_SLA", "Custom SLA"


#: BRD §6.2 rates.
ADDON_PRICES = {
    AddOnKind.EXTRA_ENTITY: Decimal("79.00"),
    AddOnKind.APPROVAL_WORKFLOW: Decimal("99.00"),
    AddOnKind.ERP_SYNC: Decimal("149.00"),
    AddOnKind.CUSTOM_SLA: Decimal("199.00"),
}

#: Add-ons that are inherently one-per-subscription; only extra entities
#: carry a meaningful quantity.
SINGLE_QUANTITY_KINDS = (
    AddOnKind.APPROVAL_WORKFLOW,
    AddOnKind.ERP_SYNC,
    AddOnKind.CUSTOM_SLA,
)


class EnterpriseAddOn(BaseModel):
    """An Enterprise extra, billed as its own line (E9-S5).

    Separate rows rather than one opaque "custom" charge, so finance can see
    what was actually sold — that is the entire requirement.
    """

    subscription = models.ForeignKey(
        "billing.Subscription",
        on_delete=models.CASCADE,
        related_name="addons",
    )

    kind = models.CharField(max_length=30, choices=AddOnKind.choices)

    quantity = models.PositiveIntegerField(default=1)

    # Captured at sale time. Enterprise is negotiated, so a later rate change
    # must not silently reprice a signed contract.
    unit_price = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        db_table = "enterprise_addons"
        ordering = ["kind"]
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "kind"],
                name="uniq_addon_kind_per_subscription",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="addon_quantity_positive",
            ),
        ]

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.kind} x{self.quantity} @ {self.unit_price}"
