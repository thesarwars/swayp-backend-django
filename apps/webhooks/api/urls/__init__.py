from django.urls import path

from apps.webhooks.api.views.processors import (
    LobWebhookAPIView,
    MockWebhookAPIView,
    PlaidWebhookAPIView,
    StripeWebhookAPIView,
)

_PROCESSORS = (
    ("stripe", StripeWebhookAPIView),
    ("lob", LobWebhookAPIView),
    ("plaid", PlaidWebhookAPIView),
    ("mock", MockWebhookAPIView),
)


def build(name_suffix=""):
    """One route per processor, buildable twice under different names.

    Two names for one view rather than two views: a second registration of
    the same path with the same name would silently win ``reverse()`` and
    nothing would say which mount you got.
    """
    return [
        path(
            f"/{slug}",
            view.as_view(),
            name=f"webhook-{slug}{name_suffix}",
        )
        for slug, view in _PROCESSORS
    ]


#: The canonical mount, versionless at /webhooks/ — a processor-registered
#: URL must never move with an API version, and ``reverse()`` still gives
#: this one.
urlpatterns = build()

#: The same views under /api/v1/webhooks/, because that is what is already
#: registered in the Plaid dashboard. An alias rather than a move:
#: re-pointing a processor at a new URL means a window where events land
#: nowhere, and events that land nowhere are payments that never confirm.
versioned_urlpatterns = build("-v1")
