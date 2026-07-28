from django.test import SimpleTestCase

from apps.common.tasks import health_check


class CeleryHealthTaskTests(SimpleTestCase):

    def test_health_check_runs(self):
        # CELERY_TASK_ALWAYS_EAGER is on in verify settings; calling the task
        # synchronously must return "ok".
        self.assertEqual(health_check.apply().get(), "ok")

    def test_celery_app_importable(self):
        from config import celery_app

        self.assertEqual(celery_app.main, "config")
        self.assertEqual(
            celery_app.conf.timezone,
            "America/New_York",
        )
