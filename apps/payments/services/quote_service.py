"""What each rail would cost and when it would land, before creating (PAY-5).

The pay screens need the offer up front: which rails this bill can take,
the fee for each, and the dates. Creating a payment to find out reserves the
bill and has to be cancelled again, and the client cannot work out fees or
the same-day cutoff itself without re-implementing Eastern-time rules.

Nothing is created or charged. The figures come from the same functions
create and the fee service use, so the quote and the payment agree.
"""

from decimal import Decimal

from django.utils import timezone

from apps.billing.models import FEE_AMOUNTS, AllowanceKind, FeeKind
from apps.common.dates import estimated_arrival, initiation_date
from apps.common.enums import PaymentRail
from apps.payments.services.payment_create_service import PaymentCreateService
from apps.payments.services.rails import (
    method_for_bill,
    rail_for_bill,
    rails_for_bill,
)

#: Every rail, in the order the pay screen lists them.
QUOTED_RAILS = (
    PaymentRail.ACH_STANDARD,
    PaymentRail.ACH_SAMEDAY,
    PaymentRail.CHECK,
    PaymentRail.NETWORK,
)

FREE = Decimal("0.00")


class PaymentQuoteService:

    def quote(self, *, user, occurrence_ids, scheduled_for=None, today=None,
              now=None):
        today = today or timezone.localdate()
        now = now or timezone.now()

        occurrences = PaymentCreateService()._load_occurrences(
            user, occurrence_ids
        )

        subscription = self._subscription(user)

        # Execution charges no fee at all without a plan, so neither does the
        # quote: the two must agree.
        self.charges_fees = subscription is not None

        # Free checks left this period; None is unlimited. Counted down as
        # the quote goes, so the second check in a batch is priced as the
        # second check. It assumes every quoted check is sent.
        free_checks = self._free_checks(subscription)

        quotes = []

        for occurrence in occurrences:
            rows = []

            for rail in QUOTED_RAILS:
                row = self._rail_row(
                    occurrence, rail, scheduled_for, today, now, free_checks
                )

                if row["rail"] == PaymentRail.CHECK and row["available"]:
                    if free_checks is not None:
                        free_checks = max(free_checks - 1, 0)

                rows.append(row)

            quotes.append(
                {
                    "occurrence_id": occurrence.id,
                    "default_rail": rail_for_bill(occurrence.bill),
                    "rails": rows,
                }
            )

        return {"occurrences": quotes}

    def _rail_row(self, occurrence, rail, scheduled_for, today, now,
                  free_checks):
        from apps.billing.services.fee_service import FeeService

        anchor = scheduled_for or occurrence.due_date
        initiated = max(initiation_date(anchor, rail), today)
        allowed = rails_for_bill(occurrence.bill)

        reason = None

        if not allowed:
            # Names the provider and what to do: every bill the bank scan
            # imports starts here, because the importer has no routing
            # details for a vendor it found in a transaction description.
            # The client shows this string verbatim.
            reason = (
                f"No payment details saved for "
                f"{occurrence.bill.vendor.name}. Add how to pay this "
                f"provider first."
            )
        elif rail not in allowed:
            # ``method_for_bill``, not ``bill.payment_method``: a bill may be
            # paid by its vendor's primary method and name none of its own,
            # in which case ``allowed`` is non-empty while the bill's own
            # field is None — reading .method_type off it raised here.
            reason = (
                f"This vendor is paid by "
                f"{method_for_bill(occurrence.bill).method_type}."
            )
        elif rail == PaymentRail.ACH_SAMEDAY and not FeeService().same_day_available(
            now=now, send_date=initiated
        ):
            reason = "Past today's same-day cutoff."

        row = {
            "rail": rail,
            "available": reason is None,
            "unavailable_reason": reason,
            "fee": self._fee(rail, free_checks) if self.charges_fees else FREE,
            "initiated_date": initiated,
            "estimated_arrival": estimated_arrival(initiated, rail),
            "expedited": None,
        }

        if rail == PaymentRail.CHECK:
            expedited_start = max(
                initiation_date(anchor, rail, expedited=True), today
            )
            row["expedited"] = {
                "fee": (
                    FEE_AMOUNTS[FeeKind.EXPEDITED_CHECK]
                    if self.charges_fees
                    else FREE
                ),
                "estimated_arrival": estimated_arrival(
                    expedited_start, rail, expedited=True
                ),
            }

        return row

    @staticmethod
    def _fee(rail, free_checks):
        if rail == PaymentRail.ACH_SAMEDAY:
            return FEE_AMOUNTS[FeeKind.SAME_DAY_ACH]

        if rail == PaymentRail.CHECK and free_checks == 0:
            return FEE_AMOUNTS[FeeKind.CHECK_OVERAGE]

        return FREE

    @staticmethod
    def _subscription(user):
        from apps.billing.services.subscription_service import (
            SubscriptionService,
        )

        return SubscriptionService().current(user)

    @staticmethod
    def _free_checks(subscription):
        from apps.billing.services.allowance_service import AllowanceService

        if subscription is None:
            return None

        return AllowanceService().remaining(subscription, AllowanceKind.CHECKS)
