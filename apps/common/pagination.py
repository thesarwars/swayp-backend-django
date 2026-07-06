from django.core.paginator import EmptyPage, Paginator


class PaginationService:

    @staticmethod
    def paginate(queryset, page=1, page_size=20):
        paginator = Paginator(queryset, page_size)

        try:
            result = paginator.page(page)
        except EmptyPage:
            result = paginator.page(paginator.num_pages)

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