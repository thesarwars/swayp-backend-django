from django.urls import path

from apps.bill_categories.views.bill import BillCreateAPIView

urlpatterns = [
    path(
        "",BillCreateAPIView.as_view(),name="bill-create",
    ),
]