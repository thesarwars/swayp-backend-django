from .notification import urlpatterns as notification_urls
from .preference import urlpatterns as preference_urls

urlpatterns = [
    *notification_urls,
    *preference_urls,
]
