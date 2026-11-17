"""Starting a plan through Stripe Checkout (Phase 1).

One entry point for every plan button. The backend, not the button, decides
the route:

* a trial applies (``trial_eligible`` and the plan has trial days): the
  subscription starts now with no card, and no Stripe page is shown;
* anything else has to be paid now: a Stripe-hosted Checkout page collects
  the card and pays the first invoice, so the app never builds a card form.

A Checkout page creates the Stripe subscription itself. Swayp's own
``Subscription`` row is created by ``fulfil``, which the webhook
(``checkout.session.completed``) and the success page's poll both call. It
is idempotent: whichever arrives first creates the row, the other finds it.
"""

import datetime as dt
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.billing.models import (
    CheckoutSession,
    CheckoutStatus,
    Subscription,
    SubscriptionStatus,
)
from apps.billing.services.provider_service import (
    BillingProviderService,
    ServiceUnavailable,
)
from apps.billing.services.subscription_service import (
    SubscriptionService,
    add_month,
)
from apps.common.error_codes import ALREADY_SUBSCRIBED
from integrations.subscription_billing.base import BillingProviderError

logger = logging.getLogger(__name__)

SUBSCRIBED = "subscribed"
REDIRECT = "redirect"


class CheckoutService:

    def __init__(self, subscriptions=None, provider=None):
        self.subscriptions = subscriptions or SubscriptionService()
        self._provider_service = provider

    @property
    def provider(self):
        if self._provider_service is None:
            self._provider_service = BillingProviderService()

        return self._provider_service

    # --- starting ---------------------------------------------------------

    def start(self, *, account, plan_code):
        """Returns ``(SUBSCRIBED, subscription)`` or ``(REDIRECT, session)``."""
        if self.subscriptions.current(account) is not None:
            raise ValidationError(
                {
                    "subscription": (
                        "This account already has an active subscription. "
                        "Change the plan instead."
                    )
                },
                code=ALREADY_SUBSCRIBED,
            )

        plan = self.subscriptions.get_plan(plan_code)

        if plan.trial_days and self.subscriptions.trial_eligible(account):
            subscription = self.subscriptions.subscribe(
                account=account, plan_code=plan_code
            )
            self.close_open_sessions(account)

            return SUBSCRIBED, subscription

        return REDIRECT, self._open_session(account, plan)

    def _open_session(self, account, plan):
        now = timezone.now()

        # A second click, or a second tab, gets the page already open rather
        # than a second one that could be paid as well.
        reusable = (
            CheckoutSession.objects.filter(
                account=account,
                plan=plan,
                status=CheckoutStatus.OPEN,
                expires_at__gt=now + dt.timedelta(minutes=5),
            )
            .order_by("-created_at")
            .first()
        )

        if reusable is not None:
            return reusable

        frontend = settings.FRONTEND_URL.rstrip("/")

        try:
            ref = self.provider.provider.create_checkout_session(
                customer_id=self.provider.customer_id_for_account(account),
                price_id=self.provider.price_id(plan),
                success_url=(
                    f"{frontend}/billing/success"
                    "?session_id={CHECKOUT_SESSION_ID}"
                ),
                cancel_url=f"{frontend}/pricing?plan={plan.code}",
                metadata={"account_id": account.pk, "plan_code": plan.code},
                # Stripe returns the same session for the same key within
                # 24 hours; the minute bucket makes a deliberate retry later
                # open a fresh one.
                idempotency_key=(
                    f"checkout:{account.pk}:{plan.code}:"
                    f"{now.strftime('%Y%m%d%H%M')}"
                ),
            )
        except BillingProviderError as error:
            logger.error("could not open checkout: %s", error)

            raise ServiceUnavailable(
                "Our billing provider is temporarily unavailable. "
                "Nothing was charged — please try again."
            )

        session, _ = CheckoutSession.objects.get_or_create(
            provider_session_id=ref.id,
            defaults={
                "account": account,
                "plan": plan,
                "url": ref.url,
                "status": ref.status or CheckoutStatus.OPEN,
                "expires_at": (
                    dt.datetime.fromtimestamp(ref.expires_at, tz=dt.timezone.utc)
                    if ref.expires_at
                    else now + dt.timedelta(hours=24)
                ),
            },
        )

        if session.status == CheckoutStatus.COMPLETE:
            # The mock provider: nothing to pay, complete at once.
            self.fulfil(session.provider_session_id)
            session.refresh_from_db()

        return session

    # --- the success page ---------------------------------------------------

    def status(self, *, account, session_id):
        session = CheckoutSession.objects.filter(
            account=account, provider_session_id=session_id
        ).first()

        if session is None:
            raise NotFound("No such checkout.")

        if session.status == CheckoutStatus.OPEN:
            # The webhook may not have landed yet; ask Stripe directly.
            self.fulfil(session_id)
            session.refresh_from_db()

        return session

    # --- fulfilment -------------------------------------------------------

    @transaction.atomic
    def fulfil(self, session_id):
        """Create the Swayp subscription for a completed checkout. Safe to
        call any number of times; returns the subscription or None."""
        session = (
            CheckoutSession.objects.select_for_update()
            .select_related("plan", "account")
            .filter(provider_session_id=session_id)
            .first()
        )

        if session is None:
            logger.info("checkout %s is not one of ours", session_id)

            return None

        if session.subscription_id is not None:
            return session.subscription

        try:
            ref = self.provider.provider.get_checkout_session(
                session_id=session_id
            )
        except BillingProviderError as error:
            logger.error("could not read checkout %s: %s", session_id, error)

            return None

        if ref.status == CheckoutStatus.EXPIRED:
            session.status = CheckoutStatus.EXPIRED
            session.save(update_fields=["status", "updated_at"])

            return None

        if ref.status != CheckoutStatus.COMPLETE:
            return None

        # Serialise fulfilments per account: two checkouts paid in two tabs
        # must not both become live subscriptions.
        type(session.account).objects.select_for_update().filter(
            pk=session.account_id
        ).first()

        existing = self.subscriptions.current(session.account)

        if existing is not None:
            if existing.provider_subscription_id != ref.subscription_id:
                logger.error(
                    "checkout %s paid for account %s, which already has "
                    "subscription %s: refund and cancel %s in Stripe",
                    session_id,
                    session.account_id,
                    existing.pk,
                    ref.subscription_id,
                )

            session.status = CheckoutStatus.COMPLETE
            session.save(update_fields=["status", "updated_at"])

            return existing

        plan = session.plan
        today = timezone.localdate()

        # The founder spot is claimed here, when paid, not when the page
        # opened: near the 500th spot several pages can be open at once.
        locked = plan.price_locked and self.subscriptions.founding_lock_available()

        subscription = Subscription.objects.create(
            account=session.account,
            plan=plan,
            status=SubscriptionStatus.ACTIVE,
            period_start=today,
            period_end=add_month(today),
            locked_price=plan.monthly_price if locked else None,
            founding_claimed_at=timezone.now() if locked else None,
            provider_customer_id=self.provider.customer_id_for_account(
                session.account
            ),
            provider_subscription_id=ref.subscription_id,
            provider_status="active",
        )

        session.status = CheckoutStatus.COMPLETE
        session.subscription = subscription
        session.save(update_fields=["status", "subscription", "updated_at"])

        self.close_open_sessions(session.account)

        return subscription

    def close_open_sessions(self, account):
        """Once the account has a plan, any other Checkout page still open in
        another tab must not be payable: it would buy a second plan."""
        for session in CheckoutSession.objects.filter(
            account=account, status=CheckoutStatus.OPEN
        ):
            try:
                self.provider.provider.expire_checkout_session(
                    session_id=session.provider_session_id
                )
            except BillingProviderError as error:
                # Already completed or expired on Stripe's side; fulfil's
                # duplicate guard still catches a completed one.
                logger.warning(
                    "could not expire checkout %s: %s",
                    session.provider_session_id,
                    error,
                )

                continue

            session.status = CheckoutStatus.EXPIRED
            session.save(update_fields=["status", "updated_at"])

    def expire(self, session_id):
        CheckoutSession.objects.filter(
            provider_session_id=session_id, status=CheckoutStatus.OPEN
        ).update(status=CheckoutStatus.EXPIRED, updated_at=timezone.now())
