"""Autopay standing authorization (E4-S3 / E4-S5).

NACHA: a recurring debit needs consent the account holder actually gave, at a
moment we can point to. A beat job cannot mint that — it has to be captured in
the request where the user turned autopay on, along with the exact text they
were shown.

Enabling AUTO writes a `StandingAuthorization`. Turning it off revokes the
live one. Toggling back on captures a fresh record rather than reviving the
old, so the audit trail keeps every consent event.
"""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.bills.models.standing_authorization import StandingAuthorization
from apps.common.enums import AutopayMode


class ConsentService:

    @transaction.atomic
    def capture(self, *, bill, consent, meta):
        """Record the consent shown when autopay was enabled.

        ``consent`` is the validated ``autopay_consent`` block; ``meta`` is
        ``{"ip", "user_agent"}`` from ``apps.common.request_meta``.
        """
        if not consent or not consent.get("accepted"):
            raise ValidationError(
                {
                    "autopay_consent": (
                        "Autopay requires an accepted authorization."
                    )
                }
            )

        authorization_text = (consent.get("authorization_text") or "").strip()

        if not authorization_text:
            raise ValidationError(
                {
                    "autopay_consent": (
                        "The authorization text shown to the user is required."
                    )
                }
            )

        ip = meta.get("ip") if meta else None

        if not ip:
            # Better to refuse than to file a consent record against a
            # placeholder address.
            raise ValidationError(
                {
                    "autopay_consent": (
                        "Could not determine the client IP address, so the "
                        "authorization cannot be recorded."
                    )
                }
            )

        return StandingAuthorization.objects.create(
            bill=bill,
            authorization_text=authorization_text,
            accepted_at=timezone.now(),
            ip=ip,
            user_agent=(meta.get("user_agent") or "") if meta else "",
        )

    @transaction.atomic
    def revoke(self, *, bill):
        """Revoke every live authorization for this bill. Returns the count."""
        return self.active_authorizations(bill).update(
            revoked_at=timezone.now()
        )

    def active_authorizations(self, bill):
        return bill.standing_authorizations.filter(revoked_at__isnull=True)

    def has_active_authorization(self, bill):
        return self.active_authorizations(bill).exists()

    def sync_for_mode(self, *, bill, autopay_mode, consent, meta):
        """Bring authorizations in line with ``autopay_mode``.

        AUTO captures consent (unless a live one already covers the bill);
        REMIND revokes whatever is outstanding.
        """
        if autopay_mode == AutopayMode.AUTO:
            if self.has_active_authorization(bill):
                return None

            return self.capture(bill=bill, consent=consent, meta=meta)

        self.revoke(bill=bill)

        return None
