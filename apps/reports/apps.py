from django.apps import AppConfig


class ReportsConfig(AppConfig):
    # No migrations/ package on purpose: the app owns no tables, and the
    # absence is what makes "query-time aggregation only" structural.
    name = "apps.reports"
