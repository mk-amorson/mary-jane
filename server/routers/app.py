import time
import logging

import httpx
from fastapi import APIRouter

from ..config import get_settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/app", tags=["app"])

# ── GitHub release cache (5 min) ──

_cache: dict = {"data": None, "ts": 0.0}
_CACHE_TTL = 300


async def get_latest_release() -> dict | None:
    """Fetch latest release from GitHub API, cached for 5 min."""
    now = time.monotonic()
    if _cache["data"] and now - _cache["ts"] < _CACHE_TTL:
        return _cache["data"]

    repo = get_settings().github_repo
    if not repo:
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"https://api.github.com/repos/{repo}/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
            )
        if r.status_code != 200:
            log.warning("GitHub API %d: %s", r.status_code, r.text[:200])
            return _cache["data"]  # stale cache

        data = r.json()
        version = data["tag_name"].lstrip("v")

        # Find .exe asset
        download_url = ""
        for asset in data.get("assets", []):
            if asset["name"].endswith(".exe"):
                download_url = asset["browser_download_url"]
                break

        result = {
            "version": version,
            "download_url": download_url,
            "changelog": data.get("body", ""),
        }
        _cache["data"] = result
        _cache["ts"] = now
        return result

    except Exception:
        log.exception("GitHub release check failed")
        return _cache["data"]


@router.get("/version")
async def latest_version():
    rel = await get_latest_release()
    if rel is None:
        return {"version": None}
    return rel
