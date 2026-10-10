"""Bank link + token exchange (E5-S2).

The connection is read-only and is also Swayp's identity check on its own
paying customer (BRD §4) — owning the account is the verification. There is no
separate KYC step.
"""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.banking.models import (
    BankAccount,
    BankConnection,
    BankConnectionStatus,
)
from apps.banking.services.scan_service import MAX_MONTHS_HISTORY
from apps.common.enums import BankAccountType
from apps.common.exceptions import PlanLimitExceededException
from integrations.factory import get_bank_data_provider

#: Banks an account may connect before it has any plan (BANK-1).
NO_PLAN_BANK_LIMIT = 1

_ACCOUNT_TYPES = {
    "checking": BankAccountType.CHECKING,
    "savings": BankAccountType.SAVINGS,
}


class BankLinkService:

    def __init__(self):
        self.provider = get_bank_data_provider()

    def search_institutions(self, *, query):
        """Straight through to the provider — nothing to add or store."""
        return self.provider.search_institutions(query=query)

    def create_link_token(self, *, user, platform=None):
        token = self.provider.create_link_token(
            user_ref=str(user.id), platform=platform
        )

        return {
            "link_token": token.token,
            "expiration": token.expiration,
            # Upper case, as stored on BankConnection.provider (BANK-11): the
            # same provider must not be "mock" here and "MOCK" there.
            "provider": self.provider.name.upper(),
            "months_history": MAX_MONTHS_HISTORY,
        }

    @transaction.atomic
    def exchange(self, *, user, public_token, consent_accepted):
        """Exchange a public token for a stored connection.

        Consent is required and its timestamp is recorded — a connection with
        no recorded disclosure is not one we can rely on later.
        """
        if not consent_accepted:
            raise ValidationError(
                {
                    "consent_accepted": (
                        "Bank connection requires accepting the data-access "
                        "disclosure."
                    )
                }
            )

        # Plan ceiling before anything is created — discovering the limit
        # after the connection exists would mean tearing it back down.
        self._assert_bank_allowance(user)

        result = self.provider.exchange_public_token(
            public_token=public_token
        )

        existing = BankConnection.objects.filter(
            item_id=result.item_id
        ).first()

        if existing is not None and existing.user_id != user.id:
            # The same institution item cannot belong to two users.
            raise ValidationError(
                {"public_token": "This bank item is already linked."}
            )

        connection, _ = BankConnection.objects.update_or_create(
            item_id=result.item_id,
            defaults={
                "user": user,
                "provider": self.provider.name.upper(),
                "access_token": result.access_token,
                "institution_name": result.institution_name,
                "status": BankConnectionStatus.ACTIVE,
                "consented_at": timezone.now(),
            },
        )

        self._sync_accounts(connection, result.accounts)

        return connection

    def _assert_bank_allowance(self, user):
        """Refuse a new institution once the plan's bank limit is reached.

        Delegates to the one gate rather than counting here. Counting in both
        places is how the billing screen ended up showing "0 of 1 banks used"
        at the moment this raised 402: the gate counted live connections, the
        screen read a stored counter nothing incremented. AllowanceService
        now derives bank usage from these same rows, so the number shown and
        the number enforced cannot disagree.
        """
        # Imported here, not at module level: AllowanceService reads
        # BankConnection, so importing it up top would be a cycle.
        from apps.billing.models import AllowanceKind
        from apps.billing.services.allowance_service import AllowanceService
        from apps.billing.services.subscription_service import (
            SubscriptionService,
        )

        subscription = SubscriptionService().current(user)

        if subscription is None:
            # No subscription is not a licence to connect without limit. The
            # mobile app links a bank straight after sign-up, before any plan
            # exists (BANK-1), so one is allowed; more needs a plan. Counted
            # from the same rows AllowanceService derives bank usage from.
            connected = BankConnection.objects.filter(
                user=user, status=BankConnectionStatus.ACTIVE
            ).count()

            if connected >= NO_PLAN_BANK_LIMIT:
                raise PlanLimitExceededException(
                    "Choose a plan to connect more than one bank.",
                    limit=AllowanceKind.BANKS,
                )

            return

        AllowanceService().check_capacity(
            subscription=subscription, kind=AllowanceKind.BANKS
        )

    def _sync_accounts(self, connection, accounts):
        now = timezone.now()
        has_default = connection.accounts.filter(
            is_default_funding_source=True
        ).exists()

        for index, info in enumerate(accounts):
            account_type = _ACCOUNT_TYPES.get(
                (info.type or "").lower(), BankAccountType.CHECKING
            )

            # The first checking account becomes the funding source unless one
            # is already chosen — savings cannot fund ACH debits.
            make_default = (
                not has_default
                and account_type == BankAccountType.CHECKING
            )

            _, created = BankAccount.objects.update_or_create(
                connection=connection,
                external_id=info.account_id,
                defaults={
                    "name": info.name,
                    "mask": info.mask,
                    "account_type": account_type,
                    "available_balance": info.balance,
                    "current_balance": info.balance,
                    "balance_as_of": now,
                },
            )

            if make_default:
                BankAccount.objects.filter(
                    connection=connection, external_id=info.account_id
                ).update(is_default_funding_source=True)
                has_default = True
