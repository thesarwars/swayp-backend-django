"""Admin for the authentication models.

Like every admin table these are fully editable: the admin is the raw data
panel. Three notes:

**No hash is ever rendered.** ``RefreshToken.token_hash`` and
``PasswordHistory.password_hash`` are excluded from every form. They are
the same reason ``BankConnection.access_token`` is excluded in
``apps/banking/admin.py``: an operator has no use for the value, and password
hashes on a screen are offline cracking material that leaks through a
screenshot or a shoulder.

**OTP codes are shown.** They are stored in plain text so an operator can
read a user's code from here when email delivery fails. Anyone with admin
access can therefore sign up or reset
a password as any user whose code is live: grant admin accordingly.

**A superuser can add, change or delete any row**, including writing an OTP
code and clearing password history (which re-allows those passwords).
"""

from django.contrib import admin
from django.utils import timezone

from apps.authentication.models import OTP, PasswordHistory, RefreshToken


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    """One-time codes, shown in plain text."""

    list_display = (
        "created_at",
        "user",
        "code",
        "purpose",
        "channel",
        "expires_at",
        "is_expired",
        "is_used",
        "attempts",
    )

    list_filter = (
        "purpose",
        "channel",
        "created_at",
    )

    search_fields = ("user__email",)

    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("user",)

    readonly_fields = ("created_at", "updated_at")

    @admin.display(boolean=True, description="Expired")
    def is_expired(self, obj):
        return obj.expires_at < timezone.now()

    @admin.display(boolean=True, description="Used")
    def is_used(self, obj):
        return obj.used_at is not None




@admin.register(RefreshToken)
class RefreshTokenAdmin(admin.ModelAdmin):
    """Issued sessions. Set revoked_at to end one.

    ``user_agent`` and ``ip_address`` are here because they are what makes a
    session identifiable when a user reports one they do not recognise.
    """

    list_display = (
        "created_at",
        "user",
        "ip_address",
        "last_used_at",
        "expires_at",
        "revoked_at",
        "is_live",
    )

    list_filter = (
        "created_at",
        "revoked_at",
    )

    search_fields = (
        "user__email",
        "ip_address",
    )

    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("user",)

    exclude = ("token_hash",)

    readonly_fields = ("created_at", "updated_at")

    @admin.display(boolean=True, description="Live")
    def is_live(self, obj):
        return obj.revoked_at is None and obj.expires_at >= timezone.now()



@admin.register(PasswordHistory)
class PasswordHistoryAdmin(admin.ModelAdmin):
    """Previous password hashes, so a reset cannot reuse one (E2-S4).
    Deleting rows here re-allows those passwords."""

    list_display = (
        "created_at",
        "user",
    )

    list_filter = ("created_at",)

    search_fields = ("user__email",)

    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("user",)

    exclude = ("password_hash",)

    readonly_fields = ("created_at", "updated_at")
