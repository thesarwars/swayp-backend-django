"""Report query params and output shape (E8-S2)."""

from rest_framework import serializers
from rest_framework.settings import api_settings

from apps.common.dates import today_eastern
from apps.common.exceptions import (
    BadRequestException,
    UnprocessableEntityException,
)
from apps.common.serializers import PaginationQuerySerializer
from apps.reports.services.export_service import SUPPORTED_FORMATS

#: Earliest tax year a 1099 can be asked for. Swayp moved no money before this,
#: so anything older is a typo rather than a request.
MIN_REPORT_YEAR = 2000

#: DRF's own content-negotiation override ("format" by default). It is not a
#: report filter, so a strict query serializer has to let it through; read from
#: api_settings so a project that renames or disables it stays consistent.
_NON_FILTER_PARAMS = frozenset({api_settings.URL_FORMAT_OVERRIDE} - {None})


class _ExportSerializer(serializers.Serializer):
    """Declares ``export`` (E8-S2; PRD §10-Q4 resolved — CSV and PDF).

    This used to refuse every value, because guessing a format would have
    created a contract clients then depended on. Both formats are now
    specified, so it validates instead.

    Still narrow on purpose: an unrecognised format is a 400 naming what is
    supported, rather than a silent fallback to CSV. A client that asked for
    xlsx and received a CSV would ship it to a user as an xlsx.

    ``allow_blank`` because ``?export=`` with no value is still someone asking
    for an export: without it, Field.get_value drops a blank optional
    CharField before validate_export ever runs (rest_framework/fields.py:424)
    and the value reaches the view unvalidated.
    """

    export = serializers.CharField(required=False, allow_blank=True)

    def validate_export(self, value):
        fmt = (value or "").strip().lower()

        if fmt not in SUPPORTED_FORMATS:
            raise serializers.ValidationError(
                f"Unsupported export format. Use one of: "
                f"{', '.join(SUPPORTED_FORMATS)}."
            )

        return fmt


class ReportQuerySerializer(
    _ExportSerializer, PaginationQuerySerializer
):
    """Query params for GET reports/."""

    vendor = serializers.UUIDField(required=False, allow_null=True)
    date_from = serializers.DateField(required=False, allow_null=True)
    date_to = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")

        if date_from and date_to and date_from > date_to:
            raise UnprocessableEntityException(
                "date_from cannot be after date_to."
            )

        return attrs


class Form1099QuerySerializer(_ExportSerializer):
    """Query params for GET reports/1099/.

    Deliberately does not accept vendor/date_from/date_to: a 1099 is a tax
    year, and a caller who copies those params across from the payments report
    would otherwise get a full-year answer that looks filtered. DRF ignores
    undeclared keys rather than rejecting them, so the refusal has to be
    written out — see ``validate``.

    It does not inherit PaginationQuerySerializer either, for the same reason
    read the other way round: the response is only honest if it is whole, since
    ``rows`` plus ``unattributed`` are published as reconciling to ``totals``.
    Declaring page/pageSize would advertise — in the query params and in the
    OpenAPI schema — a slicing this endpoint does not do.
    """

    year = serializers.IntegerField(required=False)

    def validate_year(self, value):
        if value < MIN_REPORT_YEAR or value > today_eastern().year:
            raise UnprocessableEntityException(
                f"year must be between {MIN_REPORT_YEAR} and the current tax "
                "year."
            )

        return value

    def validate(self, attrs):
        unknown = sorted(
            set(self.initial_data) - set(self.fields) - _NON_FILTER_PARAMS
        )

        if unknown:
            raise BadRequestException(
                f"This report does not accept {', '.join(unknown)}. A 1099 "
                "covers one whole tax year: the only filter is ?year=."
            )

        return attrs


class _EasternDateField(serializers.DateField):
    """A stored datetime rendered as the calendar date the user lived it on.

    ``settings.TIME_ZONE`` is UTC, so a payment made at 20:00 ET would
    otherwise be filed under tomorrow. A DateField subclass rather than a
    SerializerMethodField so the wire, the OpenAPI schema and
    ``response.data`` all agree that this column is a date string.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("read_only", True)
        super().__init__(**kwargs)

    def to_representation(self, value):
        return super().to_representation(today_eastern(value))


class _RowVendorSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class _RowBillSerializer(serializers.Serializer):
    # Bill has no name field, so the row carries ids + due_date and the client
    # composes the label the way Bill.__str__ does: vendor name + cycle.
    id = serializers.UUIDField(source="bill_id")
    occurrence_id = serializers.UUIDField(source="id")
    due_date = serializers.DateField()


class ReportRowSerializer(serializers.Serializer):
    payment_id = serializers.UUIDField(source="id")
    reference = serializers.CharField(source="transaction_reference")
    date = _EasternDateField(source="created_at")
    vendor = _RowVendorSerializer(allow_null=True)
    bill = _RowBillSerializer(source="bill_occurrence", allow_null=True)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    fee = serializers.DecimalField(max_digits=18, decimal_places=2)
    total = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField()
    rail = serializers.CharField()
    status = serializers.CharField()
    initiated_date = serializers.DateField(allow_null=True)
    estimated_arrival = serializers.DateField(allow_null=True)


class _MoneyBucketSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    fee = serializers.DecimalField(max_digits=18, decimal_places=2)
    total = serializers.DecimalField(max_digits=18, decimal_places=2)


class _CurrencyBucketSerializer(_MoneyBucketSerializer):
    currency = serializers.CharField()


class ReportTotalsSerializer(_MoneyBucketSerializer):
    # Null when the filtered set is empty or spans more than one currency;
    # by_currency is then the only honest breakdown. Payment.currency allows
    # BDT/EUR/USD and nothing pins a user to one.
    currency = serializers.CharField(allow_null=True)
    by_status = serializers.DictField(child=_MoneyBucketSerializer())
    by_currency = _CurrencyBucketSerializer(many=True)


class _FiltersEchoSerializer(serializers.Serializer):
    vendor = serializers.UUIDField(allow_null=True)
    date_from = serializers.DateField(allow_null=True)
    date_to = serializers.DateField(allow_null=True)


class ReportResponseSerializer(serializers.Serializer):
    rows = ReportRowSerializer(many=True)
    totals = ReportTotalsSerializer()
    filters = _FiltersEchoSerializer()


class _Vendor1099RowSerializer(_MoneyBucketSerializer):
    vendor_id = serializers.UUIDField()
    vendor_name = serializers.CharField()


class Form1099ResponseSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    rows = _Vendor1099RowSerializer(many=True)
    totals = _MoneyBucketSerializer()
    # Successful payments with no vendor FK. Surfaced rather than dropped so
    # the vendor rows plus this block still reconcile to totals — a tax dataset
    # that silently loses money is worse than one that admits it.
    unattributed = _MoneyBucketSerializer()
