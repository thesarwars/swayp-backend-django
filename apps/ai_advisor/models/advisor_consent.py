from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class AdvisorConsent(BaseModel):
    """A user's opt-in to Flo using their financial data (E7-S1).

    One row per user. Revoking sets ``revoked_at`` rather than deleting the
    row, so consent history stays auditable and ``has_live_consent`` is a
    simple ``revoked_at IS NULL`` check.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="advisor_consent",
    )
    consented_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    consent_text = models.TextField()

    class Meta:
        db_table = "advisor_consents"

    @property
    def is_live(self) -> bool:
        return self.revoked_at is None
