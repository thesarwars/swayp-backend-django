"""Flo advisor consent (E7-S1).

The single source of truth for whether Flo may use a user's financial data.
``has_live_consent`` gates every LLM call (E7-S2/S3); revoking takes effect
immediately because the gate is checked per request, not cached.

Consent is a GLBA/CA/VT opt-in artifact, so the audit row it produces has to be
truthful about who granted it and from where. ``record`` refuses rather than
file a placeholder IP. ``revoke`` never refuses — a user must always be able to
opt out — and records a null IP honestly if the client address is unknowable.
"""

from django.db import transaction
from django.utils import timezone

from apps.ai_advisor.models import AdvisorConsent
from apps.common.exceptions import BadRequestException

DEFAULT_CONSENT_TEXT = (
    "I allow Flo to use my account balances and upcoming bills to give me "
    "cash-flow guidance. Flo never sees my account numbers or raw "
    "transactions."
)


class ConsentService:

    @staticmethod
    def has_live_consent(user) -> bool:
        return AdvisorConsent.objects.filter(
            user=user, revoked_at__isnull=True
        ).exists()

    @staticmethod
    def state(user):
        """Current consent state, including "never consented" (E7-S1).

        The settings surface has to render the toggle before anything exists,
        and POSTing to find out would itself grant consent.
        """
        consent = AdvisorConsent.objects.filter(user=user).first()

        if consent is None:
            return {
                "is_live": False,
                "consented_at": None,
                "revoked_at": None,
                "consent_text": None,
            }

        return {
            "is_live": consent.is_live,
            "consented_at": consent.consented_at,
            "revoked_at": consent.revoked_at,
            "consent_text": consent.consent_text,
        }

    @staticmethod
    @transaction.atomic
    def record(*, user, consent_text=None, ip=None, user_agent=""):
        if not ip:
            raise BadRequestException(
                "Consent could not be recorded because the client address "
                "could not be determined."
            )

        existing = AdvisorConsent.objects.filter(user=user).first()

        # Re-POSTing while consent is already live is a no-op, not a re-grant.
        # Overwriting consented_at would erase the timestamp of the opt-in
        # that actually happened, and each call would append another
        # "granted" row to a trail that records one event. E4's
        # standing-authorization capture short-circuits the same way.
        if existing is not None and existing.is_live:
            return existing

        consent, _ = AdvisorConsent.objects.update_or_create(
            user=user,
            defaults={
                "consented_at": timezone.now(),
                "revoked_at": None,
                "consent_text": consent_text or DEFAULT_CONSENT_TEXT,
            },
        )
        ConsentService._audit(
            user, "ai_advisor.consent_granted", ip, user_agent
        )
        return consent

    @staticmethod
    @transaction.atomic
    def revoke(*, user, ip=None, user_agent=""):
        consent = AdvisorConsent.objects.filter(
            user=user, revoked_at__isnull=True
        ).first()

        if consent is None:
            return None

        consent.revoked_at = timezone.now()
        consent.save(update_fields=["revoked_at", "updated_at"])
        ConsentService._audit(
            user, "ai_advisor.consent_revoked", ip, user_agent
        )
        return consent

    @staticmethod
    def _audit(user, action, ip, user_agent):
        from apps.audit.models import AuditLog

        AuditLog.objects.create(
            user=user,
            action=action,
            ip=ip or None,
            user_agent=user_agent or "",
            metadata={},
        )
