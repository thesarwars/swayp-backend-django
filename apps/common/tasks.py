from celery import shared_task


@shared_task(name="common.health_check")
def health_check():
    """Trivial task to confirm the worker is alive."""
    return "ok"
