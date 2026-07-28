from django.urls import path

from apps.ai_advisor.api.views.consent import AdvisorConsentAPIView

urlpatterns = [
    path(
        "consent/",
        AdvisorConsentAPIView.as_view(),
        name="ai-consent",
    ),
]
