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

    # Free days before the first charge. Per plan rather than a global
    # constant because the Create Account screen offers the trial on the
    # business tier while the Founder card says "Pay $49 and claim my spot" —
    # a limited locked-rate seat is claimed by paying, not by trialling.
    trial_days = models.PositiveIntegerField(default=0)

    # Cached provider-side price id (E9-S1). Created from this table on
    # first use rather than configured by hand in a dashboard, so the BRD
    # numbers stay the single source of truth and going live needs no
    # manual setup. Blank while the mock provider is in use.
    provider_price_id = models.CharField(max_length=100, blank=True)

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
        # No trial: the Founder rate is a limited spot claimed by paying for
        # it, which is what the design's "Pay $49 and claim my spot" says.
        "trial_days": 0,
    },
    PlanCode.STANDARD: {
        "name": "Standard",
        "monthly_price": Decimal("99.00"),
        "seat_limit": 10,
        "bank_limit": None,
        "free_checks_per_month": 5,
        "included_entities": 1,
        "price_locked": False,
        # "Free 14-day trial on the Business plan" — Standard is that tier.
        "trial_days": 14,
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
        # Sales-led and negotiated; a self-serve trial does not apply.
        "trial_days": 0,
    },
}


#: Every plan bills monthly; there is no annual price (BILLING-8).
BILLING_INTERVAL = "month"

#: The pricing screen's copy, from the BRD §6.2 positioning column. Not on
#: the model: it is product copy, versioned with the code, not data to edit.
PLAN_DESCRIPTIONS = {
    PlanCode.FOUNDING: (
        "The founder rate, price locked for the first 500 customers."
    ),
    PlanCode.STANDARD: "For growing teams paying from several banks.",
    PlanCode.ENTERPRISE: (
        "Multiple entities, approval workflows and ERP sync, with a "
        "dedicated account manager."
    ),
}

#: What a plan includes beyond its numbers (BRD §6.2).
PLAN_EXTRAS = {
    PlanCode.FOUNDING: ("Full access to Flo",),
    PlanCode.STANDARD: (
        "Full access to Flo",
        "1099 reporting",
        "Priority support",
    ),
    PlanCode.ENTERPRISE: (
        "Everything in Standard",
        "Approval workflows and advanced ERP sync (add-ons)",
        "Dedicated account manager",
    ),
}


def _count(n, singular, plural):
    return f"{n} {singular if n == 1 else plural}"


def plan_features(plan):
    """The pricing screen's feature lines, generated from the plan's own
    limits so they cannot disagree with what the 402 enforces."""
    features = []

    if plan.seat_limit is None:
        features.append("Unlimited team members")
    else:
        features.append(
            f"Up to {_count(plan.seat_limit, 'team member', 'team members')}"
        )

    if plan.bank_limit is None:
        features.append("Unlimited connected bank accounts")
    elif plan.bank_limit == 1:
        features.append("1 connected bank account")
    else:
        features.append(f"Up to {plan.bank_limit} connected bank accounts")

    features.append("Unlimited bills and vendors")
    features.append("Free standard ACH transfers")

    if plan.free_checks_per_month:
        features.append(
            _count(
                plan.free_checks_per_month,
                "physical check a month included",
                "physical checks a month included",
            )
        )

    if plan.included_entities > 1:
        features.append(f"Up to {plan.included_entities} entities")

    features.extend(PLAN_EXTRAS.get(plan.code, ()))

    return features
