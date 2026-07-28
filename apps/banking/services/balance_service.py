"""Balance freshness for the accounts Flo reasons about (E5 -> E7).

``BankAccount.available_balance`` is written once, at link time
(``BankLinkService._sync_accounts``), and nothing else in the system ever
touched it. Every number Flo derives from it — "Chase balance $41,200", the
balance-after, the whole balance projection — was therefore as old as the bank
connection. E7 is "Blocked by: E5 (balances)", and that dependency only holds
if the balance is actually current.

This re-reads the balance through the bank-data provider on a TTL, so a burst
of advisor calls costs one provider call rather than one per request.

A provider failure is never fatal. The stored balance and its ``balance_as_of``
stamp are left exactly as they were, and callers surface that stamp so the
client can caveat a stale number instead of presenting it as live.
"""

import logging

from django.conf import settings
from django.utils import timezone

from apps.banking.models import BankConnectionStatus
from integrations.factory import get_bank_data_provider

logger = logging.getLogger(__name__)

#: Fallback when BALANCE_MAX_AGE_SECONDS is not configured.
DEFAULT_MAX_AGE_SECONDS = 300


class BalanceService:

    def __init__(self):
        self.provider = get_bank_data_provider()

    def refresh(self, account, *, force=False, now=None):
        """Re-read ``account``'s balance if the stored one has gone stale.

        Returns the account either way — refreshed, or untouched with its
        original ``balance_as_of``. Never raises: an advisor endpoint must
        degrade to a stale-but-labelled number rather than fail.
        """
        now = now or timezone.now()

        # A disconnected or errored item has no live balance to ask for, and
        # asking would just surface the provider's auth error on a read path.
        if account.connection.status != BankConnectionStatus.ACTIVE:
            return account

        if not force and self.is_fresh(account, now=now):
            return account

        try:
            balance = self.provider.get_balance(
                access_token=account.connection.access_token,
                account_id=account.external_id,
            )
        except Exception:  # noqa: BLE001 - stale beats failing the read
            logger.warning(
                "Balance refresh failed; serving the stored balance",
                exc_info=True,
                extra={"account_id": str(account.id)},
            )
            return account

        if balance is None:
            return account

        # The provider interface exposes a single balance, which is the
        # spendable one; current_balance stays as linked rather than being
        # silently overwritten with a different quantity.
        account.available_balance = balance
        account.balance_as_of = now
        account.save(
            update_fields=[
                "available_balance",
                "balance_as_of",
                "updated_at",
            ]
        )

        return account

    @classmethod
    def is_fresh(cls, account, *, now=None):
        if account.balance_as_of is None:
            return False

        now = now or timezone.now()
        age = (now - account.balance_as_of).total_seconds()

        return age < cls.max_age_seconds()

    @staticmethod
    def max_age_seconds():
        return getattr(
            settings, "BALANCE_MAX_AGE_SECONDS", DEFAULT_MAX_AGE_SECONDS
        )
