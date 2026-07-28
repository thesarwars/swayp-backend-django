from django.contrib import admin

from apps.audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only view of the audit trail.

    Rows were being written and then reachable by nobody — no admin, no view,
    no endpoint. For a GLBA/CA/VT opt-in artifact, "recorded in the audit
    trail" has to mean producible on demand, so this is the retrieval surface.
    It is read-only in both directions: a trail an operator can edit or delete
    is not evidence of anything.
    """

    list_display = ("created_at", "user", "action", "ip")
    list_filter = ("action", "created_at")
    search_fields = ("user__email", "action", "ip")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "user",
        "action",
        "ip",
        "user_agent",
        "metadata",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
