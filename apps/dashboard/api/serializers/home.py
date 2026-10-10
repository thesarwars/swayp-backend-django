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
    items = BillOccurrenceRowSerializer(
        many=True,
        help_text="Up to 5 rows of active_tab, earliest due first.",
    )


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
        help_text=(
            "Sum of this vendor's bills due in the current calendar month "
            "(US Eastern), paid or not. 0.00 when its next bill falls in a "
            "later month."
        ),
    )
    rail = serializers.CharField(allow_null=True)
    # From the vendor list's next-bill subqueries, which preview() inherits
    # by building on VendorSelector.list, so they cost no extra query
    # (DASH-8). The same values and meaning as on GET /vendors.
    next_due = serializers.DateField(
        source="next_due_date",
        allow_null=True,
        help_text="Due date of the next unsettled bill; null if none.",
    )
    recurring_amount = serializers.DecimalField(
        source="next_amount",
        max_digits=18,
        decimal_places=2,
        allow_null=True,
        help_text="Amount of that next bill, per cycle; null if none.",
    )
    amount_period = serializers.CharField(
        source="next_frequency",
        allow_null=True,
        help_text="That bill's cadence (MONTHLY, QUARTERLY, ...); null if none.",
    )


class HomeFundingAccountSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    mask = serializers.CharField()
    display = serializers.CharField()


class HomeSerializer(serializers.Serializer):
    greeting = HomeGreetingSerializer()
    funding_account = HomeFundingAccountSerializer(
        allow_null=True,
        help_text=(
            "The account a payment would debit; null when there is none, "
            "which is when creating a payment is refused."
        ),
    )
    unread_notification_count = serializers.IntegerField(
        help_text="The signed-in person's unread notifications."
    )
    stats = HomeStatsSerializer()
    recent_bills = BillOccurrenceRowSerializer(
        many=True,
        help_text=(
            "Up to 5 occurrences due today or earlier (US Eastern), any "
            "status, newest due date first."
        ),
    )
    vendors_preview = HomeVendorPreviewSerializer(many=True)
    pay_panel = PayPanelSerializer()


class HomeResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = HomeSerializer()
