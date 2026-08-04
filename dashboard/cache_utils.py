"""Simple helpers around Django cache for Jira/Xray payloads."""

from __future__ import annotations

from typing import Any, Callable

from django.conf import settings
from django.core.cache import cache


def cached_get(key: str, producer: Callable[[], Any], timeout: int | None = None) -> Any:
    timeout = settings.JIRA_CACHE_SECONDS if timeout is None else timeout
    hit = cache.get(key)
    if hit is not None:
        return hit
    value = producer()
    cache.set(key, value, timeout)
    return value


def bust_prefix(prefix: str) -> None:
    # LocMemCache has no delete_pattern; versioned keys are preferred.
    # Keep a tiny registry of keys we care about.
    known = cache.get("_known_cache_keys", set()) or set()
    for key in list(known):
        if key.startswith(prefix):
            cache.delete(key)
            known.discard(key)
    cache.set("_known_cache_keys", known, None)


def remember_key(key: str) -> None:
    known = cache.get("_known_cache_keys", set()) or set()
    known.add(key)
    cache.set("_known_cache_keys", known, None)
