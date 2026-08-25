"""Plaid adapter for the bank-data interface (E5).

Activated by settings alone::

    BANK_DATA_PROVIDER=plaid
    PLAID_CLIENT_ID=...
    PLAID_SECRET=...
    PLAID_ENV=sandbox        # or production

Sandbox and production differ only in the host and the secret, so going live
is an ``.env`` change and a redeploy. Nothing in ``apps/banking`` knows Plaid
exists — it talks to ``BankDataProvider``.

**Read-only by construction.** Every call here reads; none of them can move
money. That is not a convention, it is what the ``transactions``/``auth``
products allow. Moving money is the money-movement provider's job, and the
only bridge between the two is ``create_processor_token`` — see its docstring
for why it does not work yet.

Credentials are read at construction rather than import, so a deployment on
``mock`` neither needs the keys nor pays for the client.
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

from django.conf import settings

from integrations.bank_data.base import (
    BankAccountInfo,
    BankDataNotReady,
    BankDataProvider,
    BankDataProviderError,
    BankReauthRequired,
    ExchangeResult,
    LinkToken,
    RecurringCandidate,
    Transaction,
)

logger = logging.getLogger(__name__)

#: Plaid's stream frequencies mapped onto the vocabulary the detector already
#: speaks (``apps.common.enums.BillFrequency``). Anything unmapped becomes
#: MONTHLY: the user confirms every candidate on the review screen, and a bill
#: shown with the wrong cadence is a correction, while one dropped for having
#: an unfamiliar frequency is invisible.
_CADENCE = {
    "WEEKLY": "WEEKLY",
    "BIWEEKLY": "WEEKLY",
    "SEMI_MONTHLY": "MONTHLY",
    "MONTHLY": "MONTHLY",
    "ANNUALLY": "QUARTERLY",
}

#: Error codes that mean "the user must re-authenticate", not "we broke".
_REAUTH_CODES = {
    "ITEM_LOGIN_REQUIRED",
    "PENDING_EXPIRATION",
    "ITEM_LOCKED",
}

#: "Ask again shortly", not "this failed". Plaid pulls transactions
#: asynchronously after an item is exchanged, so the first scan of a brand new
#: connection — the one every user makes during onboarding — reaches for
#: history that has not landed yet.
_NOT_READY_CODES = {"PRODUCT_NOT_READY"}

#: A month, for turning the caller's month count into a date window. Plaid
#: takes dates, and being a few days generous costs nothing — the detector
#: clusters by vendor, not by window edge.
_DAYS_PER_MONTH = 31

#: Plaid caps a single /transactions/get page at 500.
_PAGE_SIZE = 500


class PlaidBankDataProvider(BankDataProvider):

    name = "plaid"

    def __init__(self):
        import plaid
        from plaid.api import plaid_api

        client_id = getattr(settings, "PLAID_CLIENT_ID", "")
        secret = getattr(settings, "PLAID_SECRET", "")

        if not client_id or not secret:
            raise BankDataProviderError(
                "PLAID_CLIENT_ID and PLAID_SECRET are not set. Set them, or "
                "set BANK_DATA_PROVIDER=mock."
            )

        environment = getattr(settings, "PLAID_ENV", "sandbox").lower()
        host = getattr(plaid.Environment, environment.capitalize(), None)

        if host is None:
            raise BankDataProviderError(
                f"PLAID_ENV={environment!r} is not a Plaid environment. Use "
                "'sandbox' or 'production'."
            )

        self._plaid = plaid
        self._client = plaid_api.PlaidApi(
            plaid.ApiClient(
                plaid.Configuration(
                    host=host,
                    api_key={"clientId": client_id, "secret": secret},
                )
            )
        )

    # --- error translation --------------------------------------------------

    def _call(self, fn, request):
        """Run one Plaid call and translate its failures.

        Plaid returns its error code in the body of an ApiException rather
        than on the exception, so the code is dug out of the JSON. Losing it
        would flatten "your bank wants you to log in again" into the same
        500 as a genuine outage.
        """
        try:
            return fn(request)
        except self._plaid.ApiException as error:
            code = self._error_code(error)

            if code in _REAUTH_CODES:
                raise BankReauthRequired(code) from error

            if code in _NOT_READY_CODES:
                raise BankDataNotReady(code) from error

            logger.error("plaid call failed (%s): %s", code or "?", error)

            raise BankDataProviderError(code or str(error)) from error

    @staticmethod
    def _error_code(error) -> str:
        import json

        try:
            return json.loads(error.body or "{}").get("error_code", "")
        except (ValueError, TypeError):
            return ""

    # --- linking ------------------------------------------------------------

    def create_link_token(self, *, user_ref: str) -> LinkToken:
        from plaid.model.country_code import CountryCode
        from plaid.model.link_token_create_request import (
            LinkTokenCreateRequest,
        )
        from plaid.model.link_token_create_request_user import (
            LinkTokenCreateRequestUser,
        )
        from plaid.model.products import Products

        payload = {
            "client_name": "Swayp",
            "language": "en",
            "country_codes": [
                CountryCode(code)
                for code in getattr(settings, "PLAID_COUNTRY_CODES", ["US"])
            ],
            "user": LinkTokenCreateRequestUser(client_user_id=user_ref),
            "products": [
                Products(product)
                for product in getattr(
                    settings, "PLAID_PRODUCTS", ["transactions"]
                )
            ],
        }

        # Only sent when configured: Plaid rejects an empty redirect_uri, and
        # it is required only for OAuth institutions.
        redirect_uri = getattr(settings, "PLAID_REDIRECT_URI", "")

        if redirect_uri:
            payload["redirect_uri"] = redirect_uri

        response = self._call(
            self._client.link_token_create, LinkTokenCreateRequest(**payload)
        )

        return LinkToken(
            token=response["link_token"],
            expiration=str(response.get("expiration") or "") or None,
        )

    def exchange_public_token(self, *, public_token: str) -> ExchangeResult:
        """Trade the client's public token for a stored connection.

        Three calls, because Plaid splits what one connection means: the
        token, the accounts on it, and the institution's display name. The
        name is fetched rather than taken from the client so the row cannot be
        made to say a bank the item does not belong to.
        """
        from plaid.model.item_public_token_exchange_request import (
            ItemPublicTokenExchangeRequest,
        )

        exchanged = self._call(
            self._client.item_public_token_exchange,
            ItemPublicTokenExchangeRequest(public_token=public_token),
        )

        access_token = exchanged["access_token"]
        accounts, institution_id = self._accounts(access_token)

        return ExchangeResult(
            item_id=exchanged["item_id"],
            access_token=access_token,
            institution_name=self._institution_name(institution_id),
            accounts=accounts,
        )

    def _accounts(self, access_token: str):
        from plaid.model.accounts_get_request import AccountsGetRequest

        response = self._call(
            self._client.accounts_get,
            AccountsGetRequest(access_token=access_token),
        )

        accounts = tuple(
            BankAccountInfo(
                account_id=account["account_id"],
                mask=account.get("mask") or "",
                name=account.get("name") or "",
                # subtype ("checking") is what the app's account types are
                # keyed on; type is the broader "depository".
                type=str(account.get("subtype") or account.get("type") or ""),
                balance=_to_decimal(
                    account.get("balances", {}).get("current")
                ),
            )
            for account in response["accounts"]
        )

        return accounts, response.get("item", {}).get("institution_id")

    def _institution_name(self, institution_id) -> str:
        """Best effort — a missing display name must not fail the link.

        The connection is already made by the time this runs; refusing it here
        would strand an access token that the user has authorised and Swayp
        has not stored.
        """
        if not institution_id:
            return ""

        from plaid.model.country_code import CountryCode
        from plaid.model.institutions_get_by_id_request import (
            InstitutionsGetByIdRequest,
        )

        try:
            response = self._call(
                self._client.institutions_get_by_id,
                InstitutionsGetByIdRequest(
                    institution_id=institution_id,
                    country_codes=[
                        CountryCode(code)
                        for code in getattr(
                            settings, "PLAID_COUNTRY_CODES", ["US"]
                        )
                    ],
                ),
            )

            return response["institution"]["name"]
        except BankDataProviderError:
            logger.warning(
                "plaid institution lookup failed for %s; linking anyway",
                institution_id,
            )

            return ""

    # --- reading ------------------------------------------------------------

    def get_transactions(
        self, *, access_token: str, months: int = 12
    ) -> tuple[Transaction, ...]:
        from plaid.model.transactions_get_request import (
            TransactionsGetRequest,
        )
        from plaid.model.transactions_get_request_options import (
            TransactionsGetRequestOptions,
        )

        end = dt.date.today()
        start = end - dt.timedelta(days=months * _DAYS_PER_MONTH)

        collected: list[Transaction] = []

        while True:
            response = self._call(
                self._client.transactions_get,
                TransactionsGetRequest(
                    access_token=access_token,
                    start_date=start,
                    end_date=end,
                    options=TransactionsGetRequestOptions(
                        count=_PAGE_SIZE, offset=len(collected)
                    ),
                ),
            )

            page = response["transactions"]

            collected.extend(
                Transaction(
                    transaction_id=row["transaction_id"],
                    posted_on=row["date"],
                    name=row.get("merchant_name") or row.get("name") or "",
                    amount=_to_decimal(row.get("amount")),
                )
                for row in page
            )

            # Paged rather than taking the first 500: a year of a busy
            # business account runs past that, and the bills that fell off the
            # end would simply never be detected.
            if not page or len(collected) >= response["total_transactions"]:
                break

        return tuple(collected)

    def get_recurring(
        self, *, access_token: str
    ) -> tuple[RecurringCandidate, ...]:
        """Plaid's own recurring detection.

        Outflows only — inflows are money arriving, which is not a bill. Swayp
        does not depend on this: ``ScanService`` clusters the raw history with
        rules of its own (E5-S4), and this is a second opinion.
        """
        from plaid.model.transactions_recurring_get_request import (
            TransactionsRecurringGetRequest,
        )

        response = self._call(
            self._client.transactions_recurring_get,
            TransactionsRecurringGetRequest(access_token=access_token),
        )

        candidates = []

        for stream in response.get("outflow_streams", []):
            last_date = stream.get("last_date")

            candidates.append(
                RecurringCandidate(
                    vendor_name=(
                        stream.get("merchant_name")
                        or stream.get("description")
                        or ""
                    ),
                    amount=_to_decimal(
                        stream.get("average_amount", {}).get("amount")
                    ),
                    cadence=_CADENCE.get(
                        str(stream.get("frequency") or ""), "MONTHLY"
                    ),
                    due_day=last_date.day if last_date else 1,
                    occurrences=len(stream.get("transaction_ids") or ()),
                )
            )

        return tuple(candidates)

    def get_balance(self, *, access_token: str, account_id: str) -> Decimal:
        from plaid.model.accounts_balance_get_request import (
            AccountsBalanceGetRequest,
        )
        from plaid.model.accounts_balance_get_request_options import (
            AccountsBalanceGetRequestOptions,
        )

        response = self._call(
            self._client.accounts_balance_get,
            AccountsBalanceGetRequest(
                access_token=access_token,
                options=AccountsBalanceGetRequestOptions(
                    account_ids=[account_id]
                ),
            ),
        )

        for account in response["accounts"]:
            if account["account_id"] == account_id:
                balances = account.get("balances", {})

                # available is what can actually be spent; current includes
                # pending. Falling back rather than reporting zero, which
                # would read as an empty account.
                return _to_decimal(
                    balances.get("available")
                    if balances.get("available") is not None
                    else balances.get("current")
                )

        raise BankDataProviderError(f"No account {account_id} on this item.")

    # --- the bridge to money movement ---------------------------------------

    def create_processor_token(
        self, *, access_token: str, account_id: str, processor: str
    ) -> str:
        """Mint a token the money-movement rail can debit with.

        This is what lets Swayp keep the promise in ``apps/common/crypto.py``
        — masked last-4 and a token, never the raw numbers.

        **It does not work on the current Plaid account.** Every processor
        returns ``INVALID_PRODUCT``, including after enabling ``auth`` on the
        item, while ``/auth/get`` on that same item succeeds. Processor tokens
        are a per-partner entitlement granted on the Plaid account, so this
        is written to the documented shapes and cannot be verified until that
        is granted. See ``docs/plaid-integration-plan.md`` §2.

        Stripe is not a value of ``processor``: it has an endpoint of its own.
        """
        if processor.lower() == "stripe":
            from plaid.model.processor_stripe_bank_account_token_create_request import (  # noqa: E501
                ProcessorStripeBankAccountTokenCreateRequest,
            )

            response = self._call(
                self._client.processor_stripe_bank_account_token_create,
                ProcessorStripeBankAccountTokenCreateRequest(
                    access_token=access_token, account_id=account_id
                ),
            )

            return response["stripe_bank_account_token"]

        from plaid.model.processor_token_create_request import (
            ProcessorTokenCreateRequest,
        )

        response = self._call(
            self._client.processor_token_create,
            ProcessorTokenCreateRequest(
                access_token=access_token,
                account_id=account_id,
                processor=processor.lower(),
            ),
        )

        return response["processor_token"]

    # --- disconnecting ------------------------------------------------------

    def remove_item(self, *, access_token: str) -> None:
        """Revoke the item at Plaid, so a disconnect is actually a disconnect.

        Without this a "disconnected" connection is only flagged locally and
        Plaid keeps refreshing it — Swayp would go on paying for an item the
        user believes they revoked, and the screen promising "all Plaid data
        deleted within 24 hours" would be false.
        """
        from plaid.model.item_remove_request import ItemRemoveRequest

        self._call(
            self._client.item_remove,
            ItemRemoveRequest(access_token=access_token),
        )


def _to_decimal(value) -> Decimal:
    """Money through str(), never float().

    ``Decimal(0.1)`` is not 0.1, and these values become bill amounts.
    """
    if value is None:
        return Decimal("0")

    return Decimal(str(value))
