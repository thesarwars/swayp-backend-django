from django.urls import path

from apps.vendors.api.views.activity import VendorActivityListAPIView
from apps.vendors.api.views.qr_views import QRDecodeAPIView
from apps.vendors.api.views.vendor_view import (
    VendorListCreateAPIView,
    VendorDetailAPIView,
    VendorSummaryAPIView,
    VendorRestoreAPIView,
)
from apps.vendors.api.views.provider import (
    ProviderDirectorySearchAPIView,
)
from apps.vendors.api.views.vendor_payment_method import (
    VendorPaymentMethodListCreateAPIView,
    VendorPaymentMethodDetailAPIView,
    SetPrimaryPaymentMethodAPIView,
)

urlpatterns = [ 
    # Vendor
    path("",VendorListCreateAPIView.as_view(),name="vendor-list-create",),
    path("/summary",VendorSummaryAPIView.as_view(),name="vendor-summary",),
    path("/activity",VendorActivityListAPIView.as_view(),name="vendor-activity"),
    path("/<uuid:vendor_id>",VendorDetailAPIView.as_view(),name="vendor-detail",),
    path("/<uuid:vendor_id>/restore",VendorRestoreAPIView.as_view(),name="vendor-restore"),
    # Vendor Payment Methods
    path("/<uuid:vendor_id>/payment-methods",VendorPaymentMethodListCreateAPIView.as_view(),name="vendor-payment-method-list-create"),
    path("/<uuid:vendor_id>/payment-methods/<uuid:method_id>",VendorPaymentMethodDetailAPIView.as_view(),name="vendor-payment-method-detail"),
    path("/<uuid:vendor_id>/payment-methods/<uuid:method_id>/set-primary",SetPrimaryPaymentMethodAPIView.as_view(),name="vendor-payment-method-set-primary"),
    # Provider Directory Search
    path("/directory-search",ProviderDirectorySearchAPIView.as_view(),name="provider-directory-search"),

    path("/qr/decode",QRDecodeAPIView.as_view(),name="vendor-qr-decode",),

]