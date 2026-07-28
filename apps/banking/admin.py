from django.contrib import admin

from .models import (
    BankAccount,
    BankConnection,
    BillDetectionCandidate,
    TransactionScan,
)


class BankAccountInline(admin.TabularInline):
    model = BankAccount
    extra = 0
    fields = ("name", "mask", "account_type", "is_default_funding_source")
    readonly_fields = fields


@admin.register(BankConnection)
class BankConnectionAdmin(admin.ModelAdmin):
    list_display = ("institution_name", "user", "status", "consented_at")
    list_filter = ("status", "provider")
    search_fields = ("institution_name", "user__email")
    inlines = [BankAccountInline]

    # access_token must never be readable through the admin (E5-S1 AC).
    exclude = ("access_token",)
    readonly_fields = ("item_id", "consented_at", "created_at", "updated_at")


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("name", "mask", "account_type", "is_default_funding_source")
    list_filter = ("account_type", "is_default_funding_source")


@admin.register(TransactionScan)
class TransactionScanAdmin(admin.ModelAdmin):
    list_display = (
        "id", "connection", "status", "transactions_scanned",
        "detected_count", "completed_at",
    )
    list_filter = ("status",)


@admin.register(BillDetectionCandidate)
class BillDetectionCandidateAdmin(admin.ModelAdmin):
    list_display = (
        "vendor_name", "amount", "cadence", "due_day", "occurrences",
        "imported_bill",
    )
    list_filter = ("cadence", "selected")
    search_fields = ("vendor_name",)
