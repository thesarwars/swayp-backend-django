from django.contrib import admin

from apps.ai_advisor.models import AdvisorConsent


@admin.register(AdvisorConsent)
class AdvisorConsentAdmin(admin.ModelAdmin):
    """Flo consent, fully editable like every admin table.

    Consent is normally granted and revoked by the user through the API;
    an operator can change or delete a row here as they could in SQL.
    """

    list_display = ("user", "consented_at", "revoked_at", "is_live")
    list_filter = ("revoked_at",)
    search_fields = ("user__email",)

    @admin.display(boolean=True, description="Live")
    def is_live(self, obj):
        return obj.is_live
