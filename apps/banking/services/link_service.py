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
from apps.common.enums import BankAccountType
from integrations.factory import get_bank_data_provider

_ACCOUNT_TYPES = {
    "checking": BankAccountType.CHECKING,
    "savings": BankAccountType.SAVINGS,
}


class BankLinkService:

    def __init__(self):
        self.provider = get_bank_data_provider()

    def create_link_token(self, *, user):
        token = self.provider.create_link_token(user_ref=str(user.id))

        return {
            "link_token": token.token,
            "expiration": token.expiration,
            "provider": self.provider.name,
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
