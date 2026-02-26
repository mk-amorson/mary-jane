"""Supabase REST API wrapper using httpx (no heavy SDK dependency)."""

import httpx
from .config import get_settings

_client: httpx.AsyncClient | None = None


def _headers() -> dict:
    s = get_settings()
    return {
        "apikey": s.supabase_key,
        "Authorization": f"Bearer {s.supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _url(path: str) -> str:
    return f"{get_settings().supabase_url}/rest/v1/{path}"


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=15.0)
    return _client


# ── generic helpers ────────────────────────────────────────

async def _select(table: str, params: dict | None = None) -> list[dict]:
    c = await _get_client()
    r = await c.get(_url(table), headers=_headers(), params=params or {})
    r.raise_for_status()
    return r.json()


async def _select_single(table: str, params: dict) -> dict | None:
    headers = {**_headers(), "Accept": "application/vnd.pgrst.object+json"}
    c = await _get_client()
    r = await c.get(_url(table), headers=headers, params=params)
    if r.status_code == 406:  # no rows
        return None
    r.raise_for_status()
    return r.json()


async def _insert(table: str, data: dict | list) -> list[dict]:
    c = await _get_client()
    r = await c.post(_url(table), headers=_headers(), json=data)
    r.raise_for_status()
    return r.json()


async def _upsert(table: str, data: dict | list, on_conflict: str = "id") -> list[dict]:
    headers = {**_headers(), "Prefer": "return=representation,resolution=merge-duplicates"}
    c = await _get_client()
    r = await c.post(
        _url(table),
        headers=headers,
        params={"on_conflict": on_conflict},
        json=data if isinstance(data, list) else [data],
    )
    r.raise_for_status()
    return r.json()


async def _select_count(table: str, params: dict) -> tuple[list[dict], int]:
    headers = {**_headers(), "Prefer": "count=exact"}
    c = await _get_client()
    r = await c.get(_url(table), headers=headers, params=params)
    r.raise_for_status()
    count_hdr = r.headers.get("content-range", "")
    total = 0
    if "/" in count_hdr:
        try:
            total = int(count_hdr.split("/")[1])
        except (ValueError, IndexError):
            pass
    return r.json(), total


# ── Users ──────────────────────────────────────────────────

async def upsert_user(
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
    photo_url: str | None = None,
) -> dict:
    data = {"telegram_id": telegram_id}
    if username is not None:
        data["username"] = username
    if first_name is not None:
        data["first_name"] = first_name
    if photo_url is not None:
        data["photo_url"] = photo_url
    rows = await _upsert("users", data, on_conflict="telegram_id")
    return rows[0] if rows else {}


async def get_user_by_telegram_id(telegram_id: int) -> dict | None:
    return await _select_single("users", {"telegram_id": f"eq.{telegram_id}"})


async def get_user_by_id(user_id: int) -> dict | None:
    return await _select_single("users", {"id": f"eq.{user_id}"})


# ── Modules ────────────────────────────────────────────────

async def get_modules() -> list[dict]:
    return await _select("modules", {
        "is_active": "eq.true",
        "order": "sort_order.asc",
    })


async def get_module(module_id: str) -> dict | None:
    return await _select_single("modules", {"id": f"eq.{module_id}"})


# ── Subscriptions ──────────────────────────────────────────

async def get_active_subscriptions(user_id: int) -> list[dict]:
    return await _select("subscriptions", {
        "user_id": f"eq.{user_id}",
        "expires_at": "gte.now()",
    })


async def create_subscription(
    user_id: int,
    module_id: str,
    days: int,
    stars_paid: int,
    transaction_id: str,
) -> dict:
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=days)
    rows = await _insert("subscriptions", {
        "user_id": user_id,
        "module_id": module_id,
        "starts_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "stars_paid": stars_paid,
        "transaction_id": transaction_id,
    })
    return rows[0] if rows else {}


# ── Items ──────────────────────────────────────────────────

async def get_items(
    server: str | None = None,
    category: str | None = None,
    search: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict], int]:
    params: dict = {
        "is_active": "eq.true",
        "has_min_price": "eq.true",
        "order": "name.asc",
    }
    if category:
        params["category"] = f"eq.{category}"
    if search:
        params["name"] = f"ilike.*{search}*"

    offset = (page - 1) * per_page
    params["offset"] = str(offset)
    params["limit"] = str(per_page)

    items_data, total = await _select_count("items", params)

    # attach price_summary if server specified
    if server and items_data:
        item_ids = [i["id"] for i in items_data]
        ids_csv = ",".join(str(i) for i in item_ids)
        prices = await _select("price_summary", {
            "server_name": f"eq.{server}",
            "item_id": f"in.({ids_csv})",
        })
        price_map = {p["item_id"]: p for p in prices}
        for item in items_data:
            ps = price_map.get(item["id"])
            item["last_price"] = ps["last_price"] if ps else None
            item["median_7d"] = ps["median_7d"] if ps else None
            item["last_updated"] = ps["last_updated"] if ps else None

    return items_data, total


async def upsert_items_bulk(items: list[dict]) -> None:
    # PostgREST bulk upsert in chunks of 500
    for i in range(0, len(items), 500):
        chunk = items[i:i + 500]
        await _upsert("items", chunk, on_conflict="id")


# ── Price History ──────────────────────────────────────────

async def add_price(
    item_id: int,
    server_name: str,
    price: int,
    user_id: int,
    source: str,
) -> dict:
    rows = await _insert("price_history", {
        "item_id": item_id,
        "server_name": server_name,
        "price": price,
        "user_id": user_id,
        "source": source,
    })
    return rows[0] if rows else {}


async def get_price_latest(item_id: int, server_name: str) -> dict | None:
    return await _select_single("price_summary", {
        "item_id": f"eq.{item_id}",
        "server_name": f"eq.{server_name}",
    })


async def get_median_for_validation(
    item_id: int, server_name: str,
) -> int | None:
    """Get current median for price validation (anti-garbage OCR)."""
    summary = await get_price_latest(item_id, server_name)
    if summary and summary.get("median_7d"):
        return int(summary["median_7d"])
    return None


# ── App Versions ───────────────────────────────────────────

async def get_latest_version() -> dict | None:
    return await _select_single("app_versions", {"is_latest": "eq.true"})
