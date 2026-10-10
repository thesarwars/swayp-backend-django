"""What happened to an account's vendors, and when (VEND-5).

An append-only log for the "Recent activities" screen. The vendor's name is
copied onto each row, so the feed still reads correctly after a rename or a
delete, and the vendor link is SET_NULL for the same reason.
"""

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class VendorActivityAction(models.TextChoices):
    CREATED = "CREATED", "Vendor added"
    UPDATED = "UPDATED", "Vendor updated"
    DELETED = "DELETED", "Vendor removed"
    RESTORED = "RESTORED", "Vendor restored"
    METHOD_ADDED = "METHOD_ADDED", "Payment method added"
    METHOD_UPDATED = "METHOD_UPDATED", "Payment method updated"
    METHOD_REMOVED = "METHOD_REMOVED", "Payment method removed"
    PRIMARY_CHANGED = "PRIMARY_CHANGED", "Primary payment method changed"


class VendorActivity(BaseModel):

    #: The account the vendor belongs to; the feed is scoped by it.
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vendor_activity",
    )

    vendor = models.ForeignKey(
        "vendors.Vendor",
        on_delete=models.SET_NULL,
        null=True,
        related_name="activity",
    )

    vendor_name = models.CharField(max_length=150)

    action = models.CharField(
        max_length=20, choices=VendorActivityAction.choices
    )

    #: Who did it: the owner or a team member. Null for system actions, such
    #: as vendors created by a bank-scan import.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "vendor_activity"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["account", "-created_at"])]


def record_vendor_activity(*, vendor, action, actor=None):
    """Append one row. Never raises into the caller's request: the feed is a
    record of what happened, and losing a row must not undo the change."""
    import logging

    try:
        VendorActivity.objects.create(
            account_id=vendor.user_id,
            vendor=vendor,
            vendor_name=vendor.name,
            action=action,
            actor=actor if getattr(actor, "pk", None) else None,
        )
    except Exception:  # noqa: BLE001 - the feed is best-effort
        logging.getLogger(__name__).warning(
            "vendor activity not recorded for %s", vendor.pk, exc_info=True
        )
