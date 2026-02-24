"""Subscription manager — checks module access with caching."""

import logging
import time

log = logging.getLogger(__name__)

# Modules that are always free
_FREE_MODULES = {"stash", "items", "queue"}

# Cache TTL in seconds
_CACHE_TTL = 3600  # 1 hour


class SubscriptionManager:
    def __init__(self, state):
        self._state = state
        self._cache: dict[str, bool] = {}
        self._cache_time: float = 0.0
        self._modules_data: list[dict] | None = None

    def has_access(self, module_id: str) -> bool:
        """Check if user has access to a module.

        Free modules: always True.
        Paid modules: requires authentication + active subscription.
        Offline: uses stale cache.
        """
        if module_id in _FREE_MODULES:
            return True

        if not self._state.is_authenticated:
            return False

        # Check cache
        now = time.monotonic()
        if now - self._cache_time < _CACHE_TTL and module_id in self._cache:
            return self._cache[module_id]

        # Return stale cache if available (offline fallback)
        if module_id in self._cache:
            return self._cache[module_id]

        return False

    async def refresh(self):
        """Fetch module access from server and update cache."""
        if not self._state.api_client or not self._state.is_authenticated:
            return

        try:
            result = await self._state.api_client.get_modules()
            if result and "modules" in result:
                self._modules_data = result["modules"]
                self._cache = {
                    m["id"]: m.get("has_access", m.get("is_free", False))
                    for m in result["modules"]
                }
                self._cache_time = time.monotonic()
                log.info("Subscription cache refreshed: %s", self._cache)
        except Exception:
            log.exception("Failed to refresh subscriptions")

    @property
    def modules(self) -> list[dict]:
        """Cached list of modules with access info."""
        return self._modules_data or []
