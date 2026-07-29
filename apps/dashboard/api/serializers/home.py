"""Home dashboard aggregate payload (D1, E8-S1).

snake_case, unlike its sibling profile_summary — the epic writes the home JSON
that way and so does every other payload in the codebase.

The bill rows are ``BillOccurrenceRowSerializer`` verbatim rather than the
epic's five keys, so a row preloaded here and a row fetched from
GET bills/occurrences/?status= are the same object and the client has one
renderer for both.
"""

from rest_framework import serializers

from apps.bills.serializers.bill_occurrence_row_serializer import (
    BillOccurrenceRowSerializer,
)

TAB_CHOICES = ("overdue", "due", "upcoming")


class HomeQuerySerializer(serializers.Serializer):
    """Query params for GET dashboard/home/."""

    # A deep link ("take me to the dashboard showing Due") only changes the
    # WHERE of the pay-panel query. An unknown value is a 400 rather than a
    # silent fall-back to the default tab.
    tab = serializers.ChoiceField(choices=TAB_CHOICES, required=False)


class HomeGreetingSerializer(serializers.Serializer):
    # blank because User.get_full_name() returns "" while first_name and
    # last_name are both unset, which is the state right after registration.
    name = serializers.CharField(allow_blank=True)


class HomeStatsSerializer(serializers.Serializer):
    due_this_month = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        source="total_due_this_month",
    )
    total_bills = serializers.IntegerField()
    paid = serializers.IntegerField(source="paid_count")


class PayPanelTabsSerializer(serializers.Serializer):
    overdue = serializers.IntegerField(source="overdue_count")
    due = serializers.IntegerField(source="due_count")
    upcoming = serializers.IntegerField(source="upcoming_count")


class PayPanelSerializer(serializers.Serializer):
    # Which tab `items` belongs to. Without it the client cannot tell whether
    # it is looking at overdue rows or the fallback, so it would have to guess
    # or re-fetch.
    active_tab = serializers.CharField()
    tabs = PayPanelTabsSerializer()
    items = BillOccurrenceRowSerializer(many=True)


class HomeVendorPreviewSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    logo = serializers.CharField(allow_blank=True)
    category = serializers.CharField(
        source="category.name",
        allow_null=True,
    )
    monthly_amount = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
    )
    rail = serializers.CharField(allow_null=True)


class HomeSerializer(serializers.Serializer):
    greeting = HomeGreetingSerializer()
    stats = HomeStatsSerializer()
    recent_bills = BillOccurrenceRowSerializer(many=True)
    vendors_preview = HomeVendorPreviewSerializer(many=True)
    pay_panel = PayPanelSerializer()


class HomeResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = HomeSerializer()
