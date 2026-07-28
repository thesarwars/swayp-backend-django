from django.contrib import admin

from apps.ai_advisor.models import AdvisorConsent


@admin.register(AdvisorConsent)
class AdvisorConsentAdmin(admin.ModelAdmin):
    """Read-only view of Flo consent.

    Consent is granted and revoked by the user through the API, and the row
    is the artifact proving they did. Adding one by hand would fabricate a
    consent that never happened; deleting one would destroy the evidence that
    it did — and the add form could not have worked anyway, since every field
    it needs is read-only.
    """

    list_display = ("user", "consented_at", "revoked_at", "is_live")
    list_filter = ("revoked_at",)
    search_fields = ("user__email",)
    readonly_fields = ("consented_at", "revoked_at", "consent_text")

    @admin.display(boolean=True, description="Live")
    def is_live(self, obj):
        return obj.is_live

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
