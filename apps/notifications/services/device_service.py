"""Device registration for push (E8-S5).

Registration is idempotent and it *moves* a device between users rather than
duplicating it. A client re-registers on every launch — that is how FCM token
rotation is meant to be handled — so this runs far more often than a user
signs in, and it has to be cheap and safe to repeat.

The reassignment case is the one worth stating plainly: if a token already
exists under a different account, the row is handed to the new user. The
alternative is two rows for one physical device, and the previous account's
bill reminders continuing to arrive on a phone that has since been signed into
by someone else.
"""

import logging

from django.db import transaction

from apps.notifications.models import DeviceToken

logger = logging.getLogger(__name__)


class DeviceService:

    @transaction.atomic
    def register(self, *, user, token, platform, device_name=""):
        """Create, move, or refresh the row for this token."""
        existing = DeviceToken.objects.select_for_update().filter(
            token=token
        ).first()

        if existing is None:
            return DeviceToken.objects.create(
                user=user,
                token=token,
                platform=platform,
                device_name=device_name,
            )

        if existing.user_id != user.pk:
            logger.info(
                "push: token reassigned from user %s to %s",
                existing.user_id,
                user.pk,
            )

        existing.user = user
        existing.platform = platform
        existing.device_name = device_name
        # Reactivated deliberately: a token FCM previously rejected becomes
        # deliverable again after a reinstall, and the client proving it is
        # alive by registering is exactly that signal.
        existing.is_active = True
        existing.save(
            update_fields=[
                "user",
                "platform",
                "device_name",
                "is_active",
                "last_seen_at",
                "updated_at",
            ]
        )

        return existing

    def unregister(self, *, user, token):
        """Sign this device out of push. Idempotent.

        Scoped to the caller's own rows: a token is a bearer string that any
        client can present, and without the user filter one account could
        silence another's device by sending its token here.
        """
        return DeviceToken.objects.filter(
            user=user, token=token
        ).update(is_active=False)

    def deactivate_tokens(self, *, tokens):
        """Mark tokens the provider called permanently undeliverable.

        Not scoped to a user: this is the provider's verdict about a device,
        and the row may since have been reassigned.
        """
        if not tokens:
            return 0

        return DeviceToken.objects.filter(token__in=tokens).update(
            is_active=False
        )

    def active_tokens_for(self, user):
        return self.active_tokens_for_id(user.pk)

    def active_tokens_for_id(self, user_id):
        """By id, because the send runs in a worker that was handed an id.

        Re-reading at send time rather than accepting a frozen list is what
        makes a device signed out between enqueue and delivery actually stop
        receiving.
        """
        return tuple(
            DeviceToken.objects.filter(
                user_id=user_id, is_active=True
            ).values_list("token", flat=True)
        )
