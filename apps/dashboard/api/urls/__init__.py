from .home import urlpatterns as home_urls
from .profile_summary import urlpatterns as profile_summary_urls

urlpatterns = [
    *profile_summary_urls,
    *home_urls,
]
