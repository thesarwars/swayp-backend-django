"""The biller-directory entry a decoded QR names, if any.

Shared by vendors/qr/decode and bills/qr/decode (web C9), which answered
the same QR with and without it.
"""

from apps.providers.models import Provider


def directory_match(vendor_name):
    if not vendor_name:
        return None

    provider = (
        Provider.objects.filter(
            provider_name__icontains=vendor_name,
            status=Provider.Status.ACTIVE,
        )
        .select_related("category")
        .only(
            "id",
            "provider_name",
            "category__name",
            "supports_auto_pay",
            "status",
        )
        .first()
    )

    if provider is None:
        return None

    return {
        "id": str(provider.id),
        "provider_name": provider.provider_name,
        "category": provider.category.name if provider.category else None,
        "supports_auto_pay": provider.supports_auto_pay,
        "verified": provider.status == Provider.Status.ACTIVE,
    }
