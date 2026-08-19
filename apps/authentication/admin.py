"""Admin for the authentication models.

All three tables are security records rather than content, which shapes what
this exposes. Two rules run through it:

**No hash is ever rendered.** ``OTP.code_hash``, ``RefreshToken.token_hash``
and ``PasswordHistory.password_hash`` are excluded from every form. They are
the same reason ``BankConnection.access_token`` is excluded in
``apps/banking/admin.py``: an operator has no use for the value, and password
hashes on a screen are offline cracking material that leaks through a
screenshot or a shoulder.

**Nothing that grants access is editable.** An operator who could write
``code_hash`` could set a known OTP and verify as any user, and one who could
clear ``PasswordHistory`` could re-enable a password a reset already refused.
The single exception is ``RefreshToken.revoked_at``, because killing a live
session is the reason to open that table at all.
"""

from django.contrib import admin
from django.utils import timezone

from apps.authentication.models import OTP, PasswordHistory, RefreshToken


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    """Read-only, except that expired rows can be cleared out.

    Delete is left on deliberately: spent and expired codes accumulate and
    removing them is housekeeping, not a loss of evidence — the audit trail is
    in ``apps.audit``, not here.
    """

    list_display = (
        "created_at",
        "user",
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

    exclude = ("code_hash",)

    readonly_fields = (
        "user",
        "purpose",
        "channel",
        "expires_at",
        "used_at",
        "attempts",
        "created_at",
        "updated_at",
    )

    @admin.display(boolean=True, description="Expired")
    def is_expired(self, obj):
        return obj.expires_at < timezone.now()

    @admin.display(boolean=True, description="Used")
    def is_used(self, obj):
        return obj.used_at is not None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(RefreshToken)
class RefreshTokenAdmin(admin.ModelAdmin):
    """Issued sessions, with revocation as the one write.

    ``user_agent`` and ``ip_address`` are here because they are what makes a
    session identifiable when a user reports one they do not recognise.
    """

    list_display = (
        "created_at",
        "user",
        "ip_address",
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

    readonly_fields = (
        "user",
        "user_agent",
        "ip_address",
        "expires_at",
        "created_at",
        "updated_at",
    )

    @admin.display(boolean=True, description="Live")
    def is_live(self, obj):
        return obj.revoked_at is None and obj.expires_at >= timezone.now()

    def has_add_permission(self, request):
        # A session is issued by verifying an OTP, never by hand — a row typed
        # in here would carry a token_hash nobody holds the token for.
        return False


@admin.register(PasswordHistory)
class PasswordHistoryAdmin(admin.ModelAdmin):
    """Read-only in both directions, like the audit trail.

    The rows exist so a reset cannot reuse an old password (E2-S4). A history
    an operator can edit or delete does not enforce anything, so this only
    answers "how many, and when".
    """

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

    readonly_fields = (
        "user",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
