from decimal import Decimal

from django.db import models

from apps.common.models import BaseModel


class PlanCode(models.TextChoices):
    FOUNDING = "FOUNDING", "Founding"
    STANDARD = "STANDARD", "Standard"
    ENTERPRISE = "ENTERPRISE", "Enterprise"


class Plan(BaseModel):
    """A subscription tier (E9-S1).

    Every number here is fixed by BRD §6.2 and seeded by migration — nothing
    about pricing is invented in code. ``null`` on a limit means unlimited,
    which is why the limit fields are nullable rather than defaulting to a
    large sentinel.
    """

    code = models.CharField(
        max_length=20,
        choices=PlanCode.choices,
        unique=True,
    )

    name = models.CharField(max_length=50)

    # Enterprise stores its $299 base here; add-ons are separate line items
    # (E9-S5) so finance can see what was actually sold.
    monthly_price = models.DecimalField(max_digits=18, decimal_places=2)

    seat_limit = models.PositiveIntegerField(null=True, blank=True)
    bank_limit = models.PositiveIntegerField(null=True, blank=True)

    free_checks_per_month = models.PositiveIntegerField(default=0)

    included_entities = models.PositiveIntegerField(default=1)

    # Founding is price-locked for the first 500 customers, so a later price
    # rise must not reach an existing subscription.
    price_locked = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "plans"
        ordering = ["monthly_price"]

    @property
    def has_unlimited_seats(self):
        return self.seat_limit is None

    @property
    def has_unlimited_banks(self):
        return self.bank_limit is None

    def __str__(self):
        return f"{self.name} (${self.monthly_price}/mo)"


#: BRD §6.2, verbatim. Referenced by the seed migration and by tests, so the
#: numbers live in exactly one place.
PLAN_SPECS = {
    PlanCode.FOUNDING: {
        "name": "Founding",
        "monthly_price": Decimal("49.00"),
        "seat_limit": 3,
        "bank_limit": 1,
        "free_checks_per_month": 2,
        "included_entities": 1,
        "price_locked": True,
    },
    PlanCode.STANDARD: {
        "name": "Standard",
        "monthly_price": Decimal("99.00"),
        "seat_limit": 10,
        "bank_limit": None,
        "free_checks_per_month": 5,
        "included_entities": 1,
        "price_locked": False,
    },
    PlanCode.ENTERPRISE: {
        "name": "Enterprise",
        # Base only. Add-ons are billed separately (E9-S5).
        "monthly_price": Decimal("299.00"),
        "seat_limit": None,
        "bank_limit": None,
        "free_checks_per_month": 5,
        "included_entities": 3,
        "price_locked": False,
    },
}
