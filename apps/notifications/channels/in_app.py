from apps.notifications.channels.base import (
    IN_APP,
    SENT,
    NotificationChannel,
)
from apps.notifications.models import Notification


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

        return SENT
