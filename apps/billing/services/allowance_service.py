"""Plan allowances: capacity ceilings and metered usage (E9-S2).

Two different shapes behind one model:

- **capacity** (seats, banks) is a standing ceiling checked before an add.
  It does not reset — a seat you hold this month you still hold next month.
- **metered** (checks) is consumed over a cycle and resets at renewal, and
  once the free allotment is gone the next one bills as an overage.

Increments take a row lock. Two check sends landing together must not both
read "1 used" and both decide they are still inside the free allotment.
"""

import datetime as dt

from django.db import transaction
from django.utils import timezone

from apps.billing.models import (
    METERED_KINDS,
    AllowanceCounter,
    AllowanceKind,
)
from apps.common.exceptions import PlanLimitExceededException

#: Capacity counters are not period-scoped, but the unique constraint
#: includes period_start, so they pin to a fixed sentinel and never roll.
CAPACITY_PERIOD = dt.date(1970, 1, 1)


class AllowanceService:

    #: plan attribute holding the ceiling for each kind
    LIMIT_FIELD = {
        AllowanceKind.SEATS: "seat_limit",
        AllowanceKind.BANKS: "bank_limit",
        AllowanceKind.CHECKS: "free_checks_per_month",
    }

    def period_for(self, subscription, kind):
        """Which counter row applies.

        Metered kinds are scoped to the current cycle, so renewal opens a
        fresh row and the allowance resets.

        Capacity kinds pin to a sentinel instead. Scoping them to
        ``period_start`` looked right but silently reset every ceiling at
        renewal: the lookup found a new row with used=0, so a Founding
        customer got a second "first" bank every month.
        """
        if kind in METERED_KINDS:
            return subscription.period_start

        return CAPACITY_PERIOD

    def limit_for(self, subscription, kind):
        """The ceiling, or ``None`` for unlimited."""
        return getattr(subscription.plan, self.LIMIT_FIELD[kind])

    def counter(self, subscription, kind):
        counter, _ = AllowanceCounter.objects.get_or_create(
            subscription=subscription,
            kind=kind,
            period_start=self.period_for(subscription, kind),
        )

        return counter

    def used(self, subscription, kind):
        return self.counter(subscription, kind).used

    def remaining(self, subscription, kind):
        limit = self.limit_for(subscription, kind)

        if limit is None:
            return None

        return max(limit - self.used(subscription, kind), 0)

    # --- capacity ---------------------------------------------------------

    def check_capacity(self, *, subscription, kind, requested=1):
        """Raise if adding ``requested`` would breach the plan ceiling.

        Used before connecting a bank (E5) or adding a seat (E10), so the
        limit is enforced at the moment of the add rather than discovered
        later at invoice time.
        """
        limit = self.limit_for(subscription, kind)

        if limit is None:
            return True

        if self.used(subscription, kind) + requested > limit:
            raise PlanLimitExceededException(
                f"Your {subscription.plan.name} plan allows {limit} "
                f"{kind.lower()}. Upgrade to add more."
            )

        return True

    @transaction.atomic
    def consume_capacity(self, *, subscription, kind, quantity=1):
        counter = self._locked_counter(subscription, kind)

        limit = self.limit_for(subscription, kind)

        if limit is not None and counter.used + quantity > limit:
            raise PlanLimitExceededException(
                f"Your {subscription.plan.name} plan allows {limit} "
                f"{kind.lower()}. Upgrade to add more."
            )

        counter.used += quantity
        counter.save(update_fields=["used", "updated_at"])

        return counter

    @transaction.atomic
    def release_capacity(self, *, subscription, kind, quantity=1):
        """Give capacity back — a disconnected bank frees its slot."""
        counter = self._locked_counter(subscription, kind)

        counter.used = max(counter.used - quantity, 0)
        counter.save(update_fields=["used", "updated_at"])

        return counter

    # --- metered ----------------------------------------------------------

    @transaction.atomic
    def consume_metered(self, *, subscription, kind=AllowanceKind.CHECKS):
        """Record one metered use and report whether it is an overage.

        Returns ``(counter, is_overage)``. Metered usage is never blocked —
        going over bills a fee rather than refusing the send.
        """
        counter = self._locked_counter(subscription, kind)

        free = self.limit_for(subscription, kind) or 0

        # Overage is decided on the count *before* this use: with 2 free and
        # 2 already used, this third one bills.
        is_overage = counter.used >= free

        counter.used += 1
        counter.save(update_fields=["used", "updated_at"])

        return counter, is_overage

    def _locked_counter(self, subscription, kind):
        period_start = self.period_for(subscription, kind)

        # get_or_create first so the row exists, then re-select FOR UPDATE.
        AllowanceCounter.objects.get_or_create(
            subscription=subscription,
            kind=kind,
            period_start=period_start,
        )

        return AllowanceCounter.objects.select_for_update().get(
            subscription=subscription,
            kind=kind,
            period_start=period_start,
        )

    # --- cycle rollover ---------------------------------------------------

    @transaction.atomic
    def reset_metered(self, subscription):
        """Open fresh metered counters for the new cycle (E9-S2 AC).

        Capacity counters are deliberately left alone; the seats and banks in
        use did not disappear at midnight.
        """
        opened = []

        for kind in METERED_KINDS:
            counter, _ = AllowanceCounter.objects.get_or_create(
                subscription=subscription,
                kind=kind,
                period_start=subscription.period_start,
                defaults={"used": 0},
            )
            opened.append(counter)

        return opened

    def summary(self, subscription):
        """Every allowance at a glance, for the billing screen."""
        rows = {}

        for kind in AllowanceKind.values:
            limit = self.limit_for(subscription, kind)

            rows[kind] = {
                "limit": limit,
                "unlimited": limit is None,
                "used": self.used(subscription, kind),
                "remaining": self.remaining(subscription, kind),
            }

        return rows
