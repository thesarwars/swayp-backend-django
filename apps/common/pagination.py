from django.core.paginator import EmptyPage, Paginator
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """DRF pagination for generic views.

    Emits the same envelope as ``PaginationService`` below, which the
    selector-layer paths already return, so both styles agree on the wire.
    """

    page_query_param = "page"
    page_size_query_param = "pageSize"
    page_size = 20
    max_page_size = 100

    def get_paginated_response(self, data):
        paginator = self.page.paginator

        return Response(
            {
                "items": data,
                "pagination": {
                    "page": self.page.number,
                    "pageSize": self.get_page_size(self.request),
                    "totalPages": paginator.num_pages,
                    "totalItems": paginator.count,
                    "hasNext": self.page.has_next(),
                    "hasPrevious": self.page.has_previous(),
                },
            }
        )


class PaginationService:

    @staticmethod
    def paginate(queryset, page=1, page_size=20):
        paginator = Paginator(queryset, page_size)

        try:
            result = paginator.page(page)
        except EmptyPage:
            # A page past the end is empty. It used to return the last page
            # again, so an infinite scroll that asked for one page too many
            # rendered the final page twice (DASH-7).
            return {
                "items": [],
                "pagination": {
                    "page": page,
                    "pageSize": page_size,
                    "totalPages": paginator.num_pages,
                    "totalItems": paginator.count,
                    "hasNext": False,
                    "hasPrevious": paginator.count > 0,
                },
            }

        return {
            "items": list(result.object_list),
            "pagination": {
                "page": result.number,
                "pageSize": page_size,
                "totalPages": paginator.num_pages,
                "totalItems": paginator.count,
                "hasNext": result.has_next(),
                "hasPrevious": result.has_previous(),
            },
        }