from django.contrib import admin

from apps.ai_advisor.models import AdvisorConsent


@admin.register(AdvisorConsent)
class AdvisorConsentAdmin(admin.ModelAdmin):
    list_display = ("user", "consented_at", "revoked_at")
    list_filter = ("revoked_at",)
    search_fields = ("user__email",)
    readonly_fields = ("consented_at", "revoked_at", "consent_text")
