from django.test import SimpleTestCase

from apps.common.enums import Currency
from apps.payments.models import Payment


class CurrencyDefaultTests(SimpleTestCase):

    def test_payment_currency_defaults_to_usd(self):
        self.assertEqual(
            Payment._meta.get_field("currency").default,
            Currency.USD,
        )
