"""Which accounts on a bank item may fund a payment (E5-S2).

A Plaid item carries everything the user holds at that bank, not just the
current account: the sandbox's First Platypus returns fourteen accounts, of
which eight are credit cards, loans and retirement accounts. ``_sync_accounts``
mapped the narrow subtype onto ``BankAccountType``, whose only members are
CHECKING and SAVINGS, and defaulted anything unmapped to CHECKING — so a
mortgage, a 401k and an auto loan were each stored as a checking account, and
the Bank Accounts screen offered the user's mortgage as a way to pay a bill.

The fixtures below are the real type/subtype pairs Plaid's sandbox returns.
"""

from django.test import TestCase

from apps.banking.factories import BankConnectionFactory
from apps.banking.models import BankAccount
from apps.banking.services.link_service import BankLinkService
from apps.common.enums import BankAccountType
from integrations.bank_data.base import BankAccountInfo

from decimal import Decimal


def account(name, kind, subtype, mask="0000"):
    return BankAccountInfo(
        account_id=f"acc-{mask}-{subtype.replace(' ', '-')}",
        mask=mask,
        name=name,
        type=subtype,
        balance=Decimal("100.00"),
        kind=kind,
    )


#: Exactly what /accounts/get answers for ins_109508.
PLAID_SANDBOX_ITEM = (
    account("Plaid Checking", "depository", "checking", "0000"),
    account("Plaid Saving", "depository", "savings", "1111"),
    account("Plaid CD", "depository", "cd", "2222"),
    account("Plaid Credit Card", "credit", "credit card", "3333"),
    account("Plaid Money Market", "depository", "money market", "4444"),
    account("Plaid IRA", "investment", "ira", "5555"),
    account("Plaid 401k", "investment", "401k", "6666"),
    account("Plaid Student Loan", "loan", "student", "7777"),
    account("Plaid Mortgage", "loan", "mortgage", "8888"),
    account("Plaid HSA", "depository", "hsa", "9001"),
    account("Plaid Cash Management", "depository", "cash management", "9002"),
    account("Plaid Auto Loan", "loan", "auto", "9003"),
    account("Plaid Home Equity Line of Credit", "loan", "home equity", "9004"),
    account("Plaid Business Credit Card", "credit", "credit card", "9999"),
)


class AccountSyncTests(TestCase):

    def setUp(self):
        self.connection = BankConnectionFactory()
        BankLinkService()._sync_accounts(self.connection, PLAID_SANDBOX_ITEM)
        self.stored = {
            a.name: a
            for a in BankAccount.objects.filter(connection=self.connection)
        }

    def test_only_depository_accounts_are_stored(self):
        self.assertEqual(
            sorted(self.stored),
            [
                "Plaid CD",
                "Plaid Cash Management",
                "Plaid Checking",
                "Plaid HSA",
                "Plaid Money Market",
                "Plaid Saving",
            ],
        )

    def test_no_loan_or_credit_account_is_stored(self):
        """The ones that were being stored as checking accounts."""
        for name in (
            "Plaid Credit Card",
            "Plaid Business Credit Card",
            "Plaid Mortgage",
            "Plaid Auto Loan",
            "Plaid Student Loan",
            "Plaid Home Equity Line of Credit",
            "Plaid IRA",
            "Plaid 401k",
        ):
            with self.subTest(name=name):
                self.assertNotIn(name, self.stored)

    def test_a_cash_management_account_is_a_checking_account(self):
        """What Betterment and Wealthfront call a current account; ACH debits
        work, so it is a legitimate funding source."""
        self.assertEqual(
            self.stored["Plaid Cash Management"].account_type,
            BankAccountType.CHECKING,
        )

    def test_accounts_that_cannot_be_debited_are_not_checking(self):
        """A CD, an HSA and a money-market account are depository and so are
        worth showing, but none is somewhere to pull a bill payment from.
        SAVINGS keeps them out of the auto-selected funding source."""
        for name in ("Plaid CD", "Plaid HSA", "Plaid Money Market"):
            with self.subTest(name=name):
                self.assertEqual(
                    self.stored[name].account_type, BankAccountType.SAVINGS
                )

    def test_the_checking_account_funds_payments(self):
        self.assertTrue(
            self.stored["Plaid Checking"].is_default_funding_source
        )

    def test_exactly_one_account_funds_payments(self):
        self.assertEqual(
            BankAccount.objects.filter(
                connection=self.connection, is_default_funding_source=True
            ).count(),
            1,
        )

    def test_an_unknown_depository_subtype_is_stored_but_not_as_checking(self):
        """Plaid adds subtypes. A new one must not inherit the ability to be
        debited by default — storing it as CHECKING is what caused this bug."""
        connection = BankConnectionFactory()
        BankLinkService()._sync_accounts(
            connection,
            (account("Future Account", "depository", "brand new", "1234"),),
        )

        stored = BankAccount.objects.get(connection=connection)

        self.assertEqual(stored.account_type, BankAccountType.SAVINGS)
        self.assertFalse(stored.is_default_funding_source)

    def test_a_provider_that_reports_no_category_is_trusted(self):
        """The mock provider returns no category; its accounts are canned and
        fundable, so an empty value must not drop every account."""
        connection = BankConnectionFactory()
        BankLinkService()._sync_accounts(
            connection,
            (
                BankAccountInfo(
                    account_id="mock-acc-4821",
                    mask="4821",
                    name="Chase Business Checking",
                    type="checking",
                    balance=Decimal("41200.00"),
                ),
            ),
        )

        stored = BankAccount.objects.get(connection=connection)

        self.assertEqual(stored.account_type, BankAccountType.CHECKING)
        self.assertTrue(stored.is_default_funding_source)
