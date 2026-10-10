from .device import urlpatterns as device_urls
from .notification import urlpatterns as notification_urls
from .preference import urlpatterns as preference_urls
from .ws_ticket import urlpatterns as ws_ticket_urls

urlpatterns = [
    *notification_urls,
    *preference_urls,
    *device_urls,
    *ws_ticket_urls,
]
