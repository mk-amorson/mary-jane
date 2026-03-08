"""Direct Supabase REST client for items & prices (no server needed)."""

import logging

import aiohttp

log = logging.getLogger(__name__)

# Public anon key — safe to embed, RLS protects data
SUPABASE_URL = "https://etdkkwtculktjxlcojla.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImV0ZGtrd3RjdWxrdGp4bGNvamxhIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE4OTM1ODcsImV4cCI6MjA4NzQ2OTU4N30.VeA536cZR7w0Q_uJfwBCMTwsYfhpRGy9TF_rg2sD7pE"


class SupabaseClient:
    def __init__(self, url: str = "", anon_key: str = ""):
        self._url = (url or SUPABASE_URL).rstrip("/")
        self._key = anon_key or SUPABASE_ANON_KEY
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "apikey": self._key,
                    "Authorization": f"Bearer {self._key}",
                }
            )

    async def get_items(self) -> list[dict]:
        """Fetch all active items ordered by name."""
        await self._ensure_session()
        url = f"{self._url}/rest/v1/items?is_active=eq.true&order=name"
        try:
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    log.error("Supabase get_items: %d", resp.status)
                    return []
                return await resp.json()
        except aiohttp.ClientError as e:
            log.error("Supabase get_items error: %s", e)
            return []

    async def get_price_summary(self) -> list[dict]:
        """Fetch price_summary materialized view."""
        await self._ensure_session()
        url = f"{self._url}/rest/v1/price_summary"
        try:
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    log.error("Supabase get_price_summary: %d", resp.status)
                    return []
                return await resp.json()
        except aiohttp.ClientError as e:
            log.error("Supabase get_price_summary error: %s", e)
            return []

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
