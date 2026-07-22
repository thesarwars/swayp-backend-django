from django.contrib import admin
from .models import Vendor, VendorPaymentMethod

class VendorPaymentMethodInline(admin.TabularInline):
    model = VendorPaymentMethod
    extra = 0
    show_change_link = True

    fields = (
        "method_type",
        "is_primary",
        "masked_account",
        "provider",
        "payee_verified",
    )

    readonly_fields = (
        "masked_account",
    )

    def masked_account(self, obj):
        if obj.account_last4:
            return f"****{obj.account_last4}"
        return "-"

    masked_account.short_description = "Account"


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "name",
        "user",
        "category",
        "source",
        "directory_verified",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
        "source",
        "directory_verified",
        "category",
    )

    search_fields = (
        "name",
        "user__email",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    inlines = [
        VendorPaymentMethodInline
    ]



@admin.register(VendorPaymentMethod)
class VendorPaymentMethodAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "vendor",
        "method_type",
        "is_primary",
        "masked_account",
        "provider",
        "payee_verified",
    )

    list_filter = (
        "method_type",
        "is_primary",
    )

    search_fields = ("vendor__name",)
    readonly_fields = (
        "masked_account",
    )

    def masked_account(self, obj):

        if obj.account_last4:
            return f"****{obj.account_last4}"

        return "-"

    masked_account.short_description = "Account"