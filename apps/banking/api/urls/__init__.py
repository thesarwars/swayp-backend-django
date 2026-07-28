from .banking import urlpatterns as banking_urls
from .routing import urlpatterns as routing_urls

urlpatterns = [*routing_urls, *banking_urls]
