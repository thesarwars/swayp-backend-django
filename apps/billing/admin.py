"""Admin for plans, subscriptions and what they bill.

Fully editable, like every admin table: the admin is the raw data panel.
Editing a plan's price or limits here changes what new subscribers get and
what every allowance check enforces. An existing Founding subscription keeps
its locked_price. A Stripe-backed plan also needs provider_price_id to match
the price in Stripe.
"""

from django.contrib import admin

from apps.billing.models import (
    AllowanceCounter,
    EnterpriseAddOn,
    FeeCharge,
    Plan,
    Subscription,
)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "monthly_price",
        "seat_limit",
        "bank_limit",
        "free_checks_per_month",
        "included_entities",
        "trial_days",
        "price_locked",
        "is_active",
    )
    list_filter = ("is_active", "price_locked")
    ordering = ("monthly_price",)
    readonly_fields = ("created_at", "updated_at")


class EnterpriseAddOnInline(admin.TabularInline):
    model = EnterpriseAddOn
    extra = 0


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "account",
        "plan",
        "status",
        "period_start",
        "period_end",
        "trial_end",
        "cancels_on",
        "provider_status",
        "created_at",
    )
    list_filter = ("status", "plan")
    search_fields = (
        "account__email",
        "provider_customer_id",
        "provider_subscription_id",
    )
    list_select_related = ("account", "plan")
    raw_id_fields = ("account",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")
    inlines = (EnterpriseAddOnInline,)


@admin.register(EnterpriseAddOn)
class EnterpriseAddOnAdmin(admin.ModelAdmin):
    list_display = ("subscription", "kind", "quantity", "unit_price")
    list_filter = ("kind",)
    search_fields = ("subscription__account__email",)
    raw_id_fields = ("subscription",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(FeeCharge)
class FeeChargeAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "subscription",
        "kind",
        "amount",
        "state",
        "guaranteed_arrival",
        "refunded_at",
    )
    list_filter = ("kind", "state")
    search_fields = (
        "subscription__account__email",
        "payment__transaction_reference",
    )
    raw_id_fields = ("subscription", "payment")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(AllowanceCounter)
class AllowanceCounterAdmin(admin.ModelAdmin):
    list_display = ("subscription", "kind", "period_start", "used")
    list_filter = ("kind",)
    search_fields = ("subscription__account__email",)
    raw_id_fields = ("subscription",)
    readonly_fields = ("created_at", "updated_at")
