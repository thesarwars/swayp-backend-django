"""Human-facing payment reference generator (E6-S1).

``SWP-YYYYMMDD-NNNN`` — a per-day sequence, so a reference read aloud to
support carries the day it belongs to.

Uniqueness is enforced by the unique constraint on
``Payment.transaction_reference``. This generator retries on collision rather
than trusting a read-then-write, which two concurrent creates would lose.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone

PREFIX = "SWP"
SEQUENCE_WIDTH = 4
MAX_ATTEMPTS = 25


def day_prefix(today=None):
    today = today or timezone.localdate()

    return f"{PREFIX}-{today:%Y%m%d}-"


def next_reference(today=None):
    """The next unused reference for the day.

    Racy on its own by design — the caller writes inside a transaction and the
    unique constraint arbitrates. Use ``create_with_reference`` for the safe
    path.
    """
    from apps.payments.models.payment import Payment

    prefix = day_prefix(today)

    latest = (
        Payment.objects.filter(transaction_reference__startswith=prefix)
        .order_by("-transaction_reference")
        .values_list("transaction_reference", flat=True)
        .first()
    )

    sequence = 1

    if latest:
        try:
            sequence = int(latest.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            sequence = 1

    return f"{prefix}{sequence:0{SEQUENCE_WIDTH}d}"


def create_with_reference(build, today=None):
    """Call ``build(reference)`` until the reference is accepted.

    Each attempt runs in a savepoint, so a losing race raises IntegrityError
    without poisoning the surrounding transaction.
    """
    from apps.payments.models.payment import Payment

    last_error = None

    for _ in range(MAX_ATTEMPTS):
        reference = next_reference(today)

        try:
            with transaction.atomic():
                return build(reference)
        except IntegrityError as error:
            if not Payment.objects.filter(
                transaction_reference=reference
            ).exists():
                # A different constraint failed; not ours to retry.
                raise

            last_error = error

    raise last_error
