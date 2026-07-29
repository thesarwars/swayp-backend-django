"""Enterprise add-ons and the invoice preview (E9-S5).

Each add-on is its own line so finance can see what was sold, rather than one
opaque "custom" charge. The invoice preview is derived, never stored — it is
always a projection of the current subscription, add-ons and unbilled fees.
"""

from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.billing.models import (
    ADDON_PRICES,
    SINGLE_QUANTITY_KINDS,
    AddOnKind,
    EnterpriseAddOn,
    FeeState,
    PlanCode,
)


class AddOnService:

    def assert_enterprise(self, subscription):
        if subscription.plan.code != PlanCode.ENTERPRISE:
            raise ValidationError(
                {
                    "plan": (
                        "Add-ons are available on the Enterprise plan only."
                    )
                }
            )

    def entity_addon_quantity(self, subscription, entity_count):
        """Entities beyond what the plan includes (BRD §6.2: base covers 3)."""
        return max(0, entity_count - subscription.plan.included_entities)

    @transaction.atomic
    def set_addon(self, *, subscription, kind, quantity=1):
        """Add or update one add-on. Quantity 0 removes it."""
        self.assert_enterprise(subscription)

        if kind not in AddOnKind.values:
            raise ValidationError({"kind": f"Unknown add-on: {kind}."})

        if kind in SINGLE_QUANTITY_KINDS and quantity > 1:
            raise ValidationError(
                {"quantity": f"{kind} is a single add-on; quantity must be 1."}
            )

        if quantity <= 0:
            EnterpriseAddOn.objects.filter(
                subscription=subscription, kind=kind
            ).delete()
            return None

        addon, _ = EnterpriseAddOn.objects.update_or_create(
            subscription=subscription,
            kind=kind,
            defaults={
                "quantity": quantity,
                # Captured at sale time so a later rate change cannot
                # silently reprice a signed contract.
                "unit_price": ADDON_PRICES[kind],
            },
        )

        return addon

    @transaction.atomic
    def sync_entity_addon(self, *, subscription, entity_count):
        """Keep the extra-entity line in step with the real entity count."""
        return self.set_addon(
            subscription=subscription,
            kind=AddOnKind.EXTRA_ENTITY,
            quantity=self.entity_addon_quantity(subscription, entity_count),
        )

    # --- invoice ----------------------------------------------------------

    def invoice_preview(self, subscription):
        """Every line the customer would be billed this cycle.

        Derived on read: the subscription line at its effective price, one
        line per add-on, and one per unbilled fee. Refunded fees appear at
        zero rather than vanishing, so the invoice still shows the guarantee
        was honoured.
        """
        lines = []

        lines.append(
            {
                "kind": "SUBSCRIPTION",
                "description": f"{subscription.plan.name} plan",
                "quantity": 1,
                "unit_price": subscription.effective_price,
                "total": subscription.effective_price,
            }
        )

        for addon in subscription.addons.all().order_by("kind"):
            lines.append(
                {
                    "kind": addon.kind,
                    "description": addon.get_kind_display(),
                    "quantity": addon.quantity,
                    "unit_price": addon.unit_price,
                    "total": addon.line_total,
                }
            )

        for fee in subscription.fee_charges.exclude(
            state=FeeState.BILLED
        ).select_related("payment").order_by("created_at"):
            refunded = fee.state == FeeState.REFUNDED

            lines.append(
                {
                    "kind": fee.kind,
                    "description": (
                        f"{fee.get_kind_display()} — "
                        f"{fee.payment.transaction_reference}"
                        + (" (refunded)" if refunded else "")
                    ),
                    "quantity": 1,
                    "unit_price": fee.amount,
                    "total": Decimal("0.00") if refunded else fee.amount,
                }
            )

        subtotal = sum(
            (line["total"] for line in lines), Decimal("0.00")
        )

        return {
            "subscription_id": subscription.id,
            "plan": subscription.plan.code,
            "period_start": subscription.period_start,
            "period_end": subscription.period_end,
            "lines": lines,
            "subtotal": subtotal,
            "currency": "USD",
        }
