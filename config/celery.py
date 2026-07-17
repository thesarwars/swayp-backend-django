import os

from celery import Celery

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings.local",
)

app = Celery("config")

# All Celery settings live in Django settings under the CELERY_ namespace.
app.config_from_object(
    "django.conf:settings",
    namespace="CELERY",
)

# Discover tasks.py in every installed app.
app.autodiscover_tasks()


@app.task(name="config.debug_task", ignore_result=True)
def debug_task():
    return "debug-ok"
