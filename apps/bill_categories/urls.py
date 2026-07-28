from django.urls import path

from .views import BillCategoryListAPIView

urlpatterns = [
    path(
        "",
        BillCategoryListAPIView.as_view(),
        name="bill-category-list",
    ),
]
