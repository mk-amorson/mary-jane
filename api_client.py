"""Central HTTP client for server communication. JWT auth with auto-refresh."""

import asyncio
import logging

import aiohttp

from auth.token_store import TokenStore

log = logging.getLogger(__name__)


class ApiClient:
    def __init__(self, server_url: str, token_store: TokenStore):
        self._base = server_url.rstrip("/")
        self._tokens = token_store
        self._session: aiohttp.ClientSession | None = None
        self._refresh_lock = asyncio.Lock()

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self, method: str, path: str, *, json=None, params=None, auth=True,
    ) -> dict | None:
        await self._ensure_session()
        url = f"{self._base}{path}"
        headers = {}
        if auth and self._tokens.access_token:
            headers["Authorization"] = f"Bearer {self._tokens.access_token}"

        try:
            async with self._session.request(
                method, url, json=json, params=params, headers=headers,
            ) as resp:
                if resp.status == 401 and auth and self._tokens.refresh_token:
                    # Try refresh
                    refreshed = await self._refresh()
                    if refreshed:
                        headers["Authorization"] = f"Bearer {self._tokens.access_token}"
                        async with self._session.request(
                            method, url, json=json, params=params, headers=headers,
                        ) as resp2:
                            if resp2.status >= 400:
                                log.error("API %s %s → %d after refresh", method, path, resp2.status)
                                return None
                            return await resp2.json()
                    else:
                        self._tokens.clear()
                        return None

                if resp.status >= 400:
                    body = await resp.text()
                    log.error("API %s %s → %d: %s", method, path, resp.status, body[:200])
                    return None
                return await resp.json()

        except aiohttp.ClientError as e:
            log.error("API %s %s error: %s", method, path, e)
            return None

    async def _refresh(self) -> bool:
        async with self._refresh_lock:
            await self._ensure_session()
            try:
                async with self._session.post(
                    f"{self._base}/auth/refresh",
                    json={"refresh_token": self._tokens.refresh_token},
                ) as resp:
                    if resp.status != 200:
                        return False
                    data = await resp.json()
                    self._tokens.save(data["access_token"], data["refresh_token"])
                    return True
            except aiohttp.ClientError:
                return False

    # ── Auth ───────────────────────────────────────────────

    async def auth_telegram(self, auth_data: dict) -> bool:
        await self._ensure_session()
        try:
            async with self._session.post(
                f"{self._base}/auth/telegram", json=auth_data,
            ) as resp:
                if resp.status != 200:
                    log.error("Auth failed: %d", resp.status)
                    return False
                data = await resp.json()
                self._tokens.save(data["access_token"], data["refresh_token"])
                return True
        except aiohttp.ClientError as e:
            log.error("Auth error: %s", e)
            return False

    async def get_me(self) -> dict | None:
        return await self._request("GET", "/auth/me")

    # ── Modules ────────────────────────────────────────────

    async def get_modules(self) -> dict | None:
        return await self._request("GET", "/modules")

    async def request_subscription(self, module_id: str) -> dict | None:
        return await self._request("POST", f"/modules/{module_id}/subscribe")

    # ── Notifications ──────────────────────────────────────

    async def notify_queue(self, position: int, threshold: int) -> dict | None:
        return await self._request("POST", "/notify/queue", json={
            "position": position,
            "threshold": threshold,
        })

    # ── App Version ────────────────────────────────────────

    async def get_app_version(self) -> dict | None:
        return await self._request("GET", "/app/version", auth=False)
