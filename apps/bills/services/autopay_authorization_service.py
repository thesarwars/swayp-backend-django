"""Server-written autopay authorization text (BILLS-3).

The words a user agrees to are part of a NACHA standing authorization, and
they are stored verbatim. Composing them on each client meant every client
could word them differently, and none had legal's wording. The server now
writes them from the terms being authorized; the client shows the result
and sends it back with the consent.
"""

from rest_framework.exceptions import ValidationError

from apps.banking.models import BankAccount, BankConnectionStatus
from apps.common.enums import PaymentRail, VendorStatus
from apps.payments.services.authorization_text import for_recurring
from apps.payments.services.autopay_service import RAIL_BY_METHOD
from apps.vendors.models import Vendor, VendorPaymentMethod

#: Used in the text when the account has no linked bank yet.
NO_FUNDING_ACCOUNT = "my connected bank account"


class AutopayAuthorizationService:

    def preview(self, *, user, terms):
        vendor = Vendor.objects.filter(
            id=terms["vendor"], user=user, status=VendorStatus.ACTIVE
        ).first()

        if vendor is None:
            raise ValidationError({"vendor": ["Vendor not found."]})

        rail = self._rail(vendor, terms.get("payment_method"))
        funding = self._funding_account(user)

        text = for_recurring(
            vendor_name=vendor.name,
            amount=terms["amount"],
            bill_type=terms["bill_type"],
            frequency=terms["frequency"],
            start_date=terms["anchor_date"],
            funding_display=funding or NO_FUNDING_ACCOUNT,
            rail=rail,
        )

        return {"authorization_text": text, "funding_account": funding}

    @staticmethod
    def _rail(vendor, payment_method_id):
        """The rail autopay would use, by the rule rail_for_bill applies."""
        if not payment_method_id:
            return PaymentRail.ACH_STANDARD

        method = VendorPaymentMethod.objects.filter(
            id=payment_method_id, vendor=vendor
        ).first()

        if method is None:
            raise ValidationError(
                {"payment_method": ["Invalid payment method."]}
            )

        return RAIL_BY_METHOD.get(method.method_type, PaymentRail.ACH_STANDARD)

    @staticmethod
    def _funding_account(user):
        """The account autopay debits: the default funding source on an
        ACTIVE connection, the same rule payments use."""
        account = BankAccount.objects.filter(
            connection__user=user,
            connection__status=BankConnectionStatus.ACTIVE,
            is_default_funding_source=True,
        ).first()

        return account.masked_name if account else None
