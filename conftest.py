"""Suite-wide test setup."""

import pytest


@pytest.fixture(autouse=True)
def _empty_cache():
    """Each test starts with an empty cache.

    Rate limits live in the cache (the per-address OTP throttle, the
    registration limit), and the local-memory cache outlives a test. Without
    this, the tenth test to register from 127.0.0.1 would be refused for a
    reason that has nothing to do with it.
    """
    from django.core.cache import cache

    cache.clear()
    yield
