from django.core.paginator import EmptyPage, Paginator
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class _PastTheEnd:
    """Stands in for a Django page past the last one: empty, no next.

    Carries only what get_paginated_response reads, so a page past the end
    renders the normal envelope with an empty list instead of a 404.
    """

    def __init__(self, number, paginator):
        self.number = number
        self.paginator = paginator

    def has_next(self):
        return False

    def has_previous(self):
        return self.paginator.count > 0


class StandardPagination(PageNumberPagination):
    """DRF pagination for generic views.

    Emits the same envelope as ``PaginationService`` below, which the
    selector-layer paths already return, so both styles agree on the wire.
    """

    page_query_param = "page"
    page_size_query_param = "pageSize"
    page_size = 20
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        """A page past the end is empty, as in PaginationService (DASH-7).

        DRF answers it with a 404, so the two paging styles in this API
        disagreed: one repeated the last page, the other failed. A page
        number that is not a number at all is still a 404.
        """
        try:
            return super().paginate_queryset(queryset, request, view)
        except NotFound:
            raw = request.query_params.get(self.page_query_param, "")

            if not str(raw).isdigit() or int(raw) < 1:
                raise

            self.request = request
            self.page = _PastTheEnd(
                int(raw),
                self.django_paginator_class(
                    queryset, self.get_page_size(request)
                ),
            )

            return []

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