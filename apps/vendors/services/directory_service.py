"""Configured-account directory search, via the provider interface (E3-S7).

Search goes through the pluggable ``DirectoryProvider`` (mock today) rather
than hitting ``providers.Provider`` directly, so the real provider is a config
swap. Hits are cached into ``providers.Provider`` on a best-effort basis so
other surfaces can reference them — caching never blocks a search.
"""

import logging

from integrations.factory import get_directory_provider

logger = logging.getLogger(__name__)


class DirectoryService:

    @staticmethod
    def search(query):
        """Return provider ``DirectoryVendor`` DTOs for a query (or [])."""
        q = (query or "").strip()
        if not q:
            return []

        results = list(get_directory_provider().search(query=q))
        DirectoryService._cache(results)
        return results

    @staticmethod
    def _cache(results):
        """Upsert hits into providers.Provider (best-effort).

        ``Provider.category`` is a required PROTECT FK, so a vendor whose
        directory category has no matching ``BillCategory`` is simply not
        cached — the live result is still returned. Any failure here is
        logged and swallowed; caching must never break search.
        """
        from apps.bill_categories.models import BillCategory
        from apps.providers.models import Provider

        for vendor in results:
            try:
                category = BillCategory.objects.filter(
                    name__iexact=vendor.category
                ).first()

                if category is None:
                    continue

                Provider.objects.update_or_create(
                    provider_code=vendor.external_id,
                    defaults={
                        "provider_name": vendor.name,
                        "category": category,
                        "logo": "",
                        "country": "US",
                        "supports_auto_pay": True,
                    },
                )
            except Exception:  # noqa: BLE001 - cache is best-effort
                logger.warning(
                    "directory cache upsert failed for %s",
                    getattr(vendor, "external_id", "?"),
                    exc_info=True,
                )
