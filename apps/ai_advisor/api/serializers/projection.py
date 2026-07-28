import datetime as dt

from django.utils import timezone
from rest_framework import serializers

from apps.common.exceptions import UnprocessableEntityException

#: The projection walks each bill's recurrence rule out to the requested date,
#: so an unbounded date is unbounded work. Two years is well past any horizon
#: a cash-flow answer is meaningful over.
MAX_PROJECTION_DAYS = 730


class BalanceProjectionQuerySerializer(serializers.Serializer):
    """Query params for GET ai/balance-projection/ (E7-S3)."""

    account = serializers.UUIDField()
    date = serializers.DateField()

    def validate_date(self, value):
        horizon = timezone.localdate() + dt.timedelta(
            days=MAX_PROJECTION_DAYS
        )

        if value > horizon:
            raise UnprocessableEntityException(
                f"Projection date cannot be more than "
                f"{MAX_PROJECTION_DAYS} days ahead."
            )

        return value


class BalanceProjectionSerializer(serializers.Serializer):
    account_id = serializers.UUIDField()
    date = serializers.DateField()
    current_balance = serializers.DecimalField(max_digits=18, decimal_places=2)
    # When the bank last reported that balance, so the client can caveat a
    # figure the provider could not refresh.
    balance_as_of = serializers.DateTimeField(allow_null=True)
    outflow_total = serializers.DecimalField(max_digits=18, decimal_places=2)
    # Money already committed out of this account but not yet settled.
    committed_total = serializers.DecimalField(max_digits=18, decimal_places=2)
    projected_balance = serializers.DecimalField(
        max_digits=18, decimal_places=2
    )
    sufficient = serializers.BooleanField()
