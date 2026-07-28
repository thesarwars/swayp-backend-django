from django.db import models

from apps.common.models import BaseModel


class PaymentAuthorization(BaseModel):
    """Immutable NACHA consent for a payment or a batch (E6-S1).

    Attached to exactly one of the two. A batch authorization already covers
    every payment inside it, so recording both would double-count the consent.

    Rows are never updated: ``save`` refuses to modify an existing row, because
    an authorization that can be rewritten after the fact is not evidence of
    anything.
    """

    payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.PROTECT,
        related_name="authorizations",
        null=True,
        blank=True,
    )

    batch = models.ForeignKey(
        "payments.PaymentBatch",
        on_delete=models.PROTECT,
        related_name="authorizations",
        null=True,
        blank=True,
    )

    # Verbatim, including the processor name. This is the one documented place
    # a processor name may appear in user-facing text.
    authorization_text = models.TextField()

    accepted_at = models.DateTimeField()
    ip = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)

    class Meta:
        db_table = "payment_authorizations"
        ordering = ["-accepted_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(payment__isnull=False, batch__isnull=True)
                    | models.Q(payment__isnull=True, batch__isnull=False)
                ),
                name="auth_payment_xor_batch",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            raise ValueError(
                "PaymentAuthorization is immutable; recorded consent cannot "
                "be edited."
            )

        return super().save(*args, **kwargs)

    def __str__(self):
        return f"authorization {self.pk} @ {self.accepted_at:%Y-%m-%d}"
