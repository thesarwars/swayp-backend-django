from .cash_context import urlpatterns as cash_context_urls
from .consent import urlpatterns as consent_urls
from .projection import urlpatterns as projection_urls

urlpatterns = [
    *consent_urls,
    *cash_context_urls,
    *projection_urls,
]
