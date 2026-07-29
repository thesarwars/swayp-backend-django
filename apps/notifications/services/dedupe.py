"""Dedupe keys for scheduled notifications (E8-S4).

The key is the only thing between a beat job that runs twice and a user who
reads the same reminder twice, so it is enforced by a database constraint
(``Notification.dedupe_key``) rather than by a pre-flight check.
"""

from apps.common.dates import today_eastern


def dedupe_key(notification_type, occurrence_id, on_date=None):
    """``"<TYPE>:<occurrence-uuid>:<YYYY-MM-DD>"``.

    The date is Eastern. ``timezone.localdate()`` follows ``TIME_ZONE``, which
    is UTC, so it rolls over at 19:00/20:00 ET — a manual evening replay of the
    05:00 beat run would compute a different key for the same day and send
    everything a second time.

    The type is part of the key because BILL_DUE and LATE_FEE_WARNING are two
    different things to say about the same occurrence on the same day, and both
    are allowed.
    """
    on_date = on_date or today_eastern()

    return f"{notification_type}:{occurrence_id}:{on_date.isoformat()}"
