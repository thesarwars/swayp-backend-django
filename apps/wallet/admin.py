from django.contrib import admin

from .models import Wallet


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "balance",
        "currency",
        "status",
        "updated_at",
    )

    list_filter = (
        "status",
        "currency",
    )

    search_fields = (
        "user__email",
        "user__username",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )