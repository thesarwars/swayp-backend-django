"""JSON that keeps money a string (API-1).

DRF's encoder turns a Decimal into a float. Serializer DecimalFields never
reach it — they render "3200.00" themselves — but a view that sends a dict
with a raw Decimal did: payment create's total, batch status, the failure
screen, the receipt and others went out as 3200.0, while the docs, the
schema and every other money field say "3200.00". A Decimal is rendered as
its exact string here, so it cannot happen again whichever path it takes.
"""

import decimal

from rest_framework.renderers import JSONRenderer
from rest_framework.utils.encoders import JSONEncoder


class MoneySafeJSONEncoder(JSONEncoder):

    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return str(obj)

        return super().default(obj)


class SwaypJSONRenderer(JSONRenderer):
    encoder_class = MoneySafeJSONEncoder
