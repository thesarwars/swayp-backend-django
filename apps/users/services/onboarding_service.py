"""Where a signup got to (E2-S6).

Onboarding is four steps, and its progress bar promises that stopping
halfway and coming back returns you to the same place. Nothing recorded that,
so a customer who closed the tab on the payment step had no way back to it and
the client would have had to guess by probing.

(The Figma bar reads "of 5" on every screen. Product confirmed that is a
design error — there are four steps and there was never a fifth.)

**Derived, not stored.** Each step's completion is read from the thing the
step actually creates — a business name, a subscription, a payment method, a
bank connection. A stored step counter is a second copy of that truth and
drifts the moment anything changes by another route: connect a bank from
Settings and a counter still says step 4 is pending. This is the same reason
seats and banks derive rather than count (E9-S2).

The one thing that cannot be derived is a deliberate skip. Step 4 offers
"Skip for now", and no amount of looking at the data distinguishes "chose to
skip" from "has not got there yet" — so that single bit is stored.
"""

from apps.banking.models import BankConnection
from apps.billing.services.subscription_service import SubscriptionService
from apps.users.models.profile import AccountType
from apps.users.services.profile_service import ProfileService

#: Four. The Figma progress bar reads "Step n of 5" on every onboarding
#: screen, which is a design error confirmed with product on 2026-07-30 —
#: there is no fifth step and there never was. The number lives here so a
#: client renders "of 4" from the API rather than from the artwork.
TOTAL_STEPS = 4


class OnboardingService:

    def __init__(self):
        self.profiles = ProfileService()
        self.subscriptions = SubscriptionService()

    # --- per-step signals -------------------------------------------------

    def business_complete(self, account):
        """Step 1. A legal name is the only required field on that screen."""
        profile = self.profiles.get_or_create_profile(account)

        if profile.account_type != AccountType.BUSINESS:
            # An individual account never sees the business step, so it can
            # never be the thing blocking them.
            return True

        branch = self.profiles.branch(profile)

        return bool((branch.business_name or "").strip())

    def plan_complete(self, account):
        """Step 2."""
        return self.subscriptions.current(account) is not None

    def payment_complete(self, account):
        """Step 3.

        A trial satisfies this: the screen says "no card needed", so a
        trialling customer has finished the step without one. Otherwise it
        needs a real provider-side subscription — on a deployment that
        collects nothing, having a plan is all there is to have.
        """
        subscription = self.subscriptions.current(account)

        if subscription is None:
            return False

        if subscription.is_trialing():
            return True

        from apps.billing.services.provider_service import (
            BillingProviderService,
        )

        if not BillingProviderService().collects_money:
            return True

        return bool(subscription.provider_subscription_id)

    def bank_complete(self, account):
        """Step 4: the account has linked a bank, ever.

        Sticky on purpose (BANK-10). Counting only ACTIVE connections sent
        anyone who disconnected their bank, or whose bank asked them to sign
        in again (ERROR), back into the onboarding wizard. The step was done;
        reconnecting is a Settings task, not unfinished onboarding. Still
        derived from the rows, so nothing extra is stored.
        """
        return BankConnection.objects.filter(user=account).exists()

    def bank_skipped(self, account):
        """The one bit that cannot be derived.

        "Skip for now" leaves no trace in the data, and without this the
        wizard would send someone back to a step they deliberately declined
        every time they signed in.
        """
        profile = self.profiles.get_or_create_profile(account)

        return profile.onboarding_bank_skipped

    # --- the answer -------------------------------------------------------

    def state(self, account):
        steps = [
            {
                "step": 1,
                "key": "business",
                "label": "Business details",
                "complete": self.business_complete(account),
            },
            {
                "step": 2,
                "key": "plan",
                "label": "Choose a plan",
                "complete": self.plan_complete(account),
            },
            {
                "step": 3,
                "key": "payment",
                "label": "Payment method",
                "complete": self.payment_complete(account),
            },
            {
                "step": 4,
                "key": "bank",
                "label": "Connect a bank",
                "complete": self.bank_complete(account),
                "skipped": self.bank_skipped(account),
                "skippable": True,
            },
        ]

        # A skipped step is not outstanding — it is settled, just not done.
        outstanding = [
            s for s in steps
            if not s["complete"] and not s.get("skipped")
        ]

        return {
            "total_steps": TOTAL_STEPS,
            "current_step": outstanding[0]["step"] if outstanding else None,
            "complete": not outstanding,
            "steps": steps,
        }

    def skip_bank(self, account):
        profile = self.profiles.get_or_create_profile(account)
        profile.onboarding_bank_skipped = True
        profile.save(
            update_fields=["onboarding_bank_skipped", "updated_at"]
        )

        return self.state(account)
