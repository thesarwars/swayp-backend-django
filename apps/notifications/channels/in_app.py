import functools

from django.db import transaction

from apps.common.casing import with_snake_case
from apps.notifications.channels.base import (
    IN_APP,
    SENT,
    NotificationChannel,
)
from apps.notifications.models import Notification
from apps.notifications.realtime import broadcast


class InAppChannel(NotificationChannel):

    key = IN_APP
    preference_field = "in_app"

    def deliver(self, dispatch):
        # Synchronous and inside the caller's transaction: the in-app row is
        # the durable record of the event, not a delivery attempt. If it
        # cannot be written the caller's transaction should roll back, which
        # is exactly today's behaviour at every Notification.objects.create
        # call-site this replaces.
        fields = {
            "user": dispatch.user,
            "title": dispatch.title,
            "message": dispatch.message,
            "type": dispatch.type,
            "metadata": dispatch.context,
        }

        if dispatch.dedupe_key is not None:
            # Reachable only once Notification.dedupe_key exists (E8-S4):
            # until then NotificationDispatchService.notify refuses the key
            # outright, because this channel is skipped for a user who has
            # in_app switched off and a guarantee that silently lapses for
            # some users is worse than none at all.
            fields["dedupe_key"] = dispatch.dedupe_key

        dispatch.notification = Notification.objects.create(**fields)

        # The live push of this same row (E8-S5). Deliberately here rather
        # than as its own channel: the socket is a transport for the in-app
        # notification, not a separate destination a user could subscribe to
        # independently. A user with in_app switched off reaches neither,
        # which is the preference being honoured once, where it is owned.
        #
        # on_commit because a browser must never be shown a row that is about
        # to be rolled back — and because broadcasting inside the transaction
        # would put a Redis round-trip on the payment path.
        transaction.on_commit(
            functools.partial(
                self._broadcast,
                user_id=dispatch.user.pk,
                notification=dispatch.notification,
            )
        )

        return SENT

    @staticmethod
    def _broadcast(*, user_id, notification):
        """Serialised here, not in the consumer, so the socket payload and
        ``GET /notifications/`` are built from one row and cannot drift."""
        broadcast(
            user_id=user_id,
            payload=with_snake_case({
                "id": str(notification.pk),
                "type": notification.type,
                "title": notification.title,
                "message": notification.message,
                "isRead": notification.is_read,
                "createdAt": notification.created_at.isoformat(),
                "metadata": notification.metadata or {},
            }),
        )
