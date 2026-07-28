from .base import *
# Tests never touch a real mail server.
MESSAGING_PROVIDER = "mock"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
