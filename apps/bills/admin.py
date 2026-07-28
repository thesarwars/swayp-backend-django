from django.contrib import admin

from .models import Bill, BillOccurrence, StandingAuthorization


class BillOccurrenceInline(admin.TabularInline):
    model = BillOccurrence
    extra = 0
    show_change_link = True

    fields = (
        "due_date",
        "amount",
        "status",
        "paid_at",
    )


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "vendor",
        "user",
        "category",
        "amount",
        "frequency",
        "anchor_date",
        "autopay_mode",
        "source",
        "created_at",
    )

    list_filter = (
        "bill_type",
        "frequency",
        "autopay_mode",
        "source",
        "category",
    )

    search_fields = (
        "vendor__name",
        "user__email",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    inlines = [BillOccurrenceInline]


@admin.register(BillOccurrence)
class BillOccurrenceAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "bill",
        "due_date",
        "amount",
        "status",
        "paid_at",
    )

    list_filter = ("status",)

    search_fields = ("bill__vendor__name",)

    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(StandingAuthorization)
class StandingAuthorizationAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "bill",
        "accepted_at",
        "revoked_at",
        "ip",
    )

    list_filter = ("revoked_at",)

    search_fields = ("bill__vendor__name",)

    readonly_fields = (
        "created_at",
        "updated_at",
    )
