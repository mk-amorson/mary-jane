"""Sync items and prices from server to local SQLite cache."""

import logging

from modules.marketplace.database import init_db, _conn

log = logging.getLogger(__name__)


async def sync_items(api_client, server: str, category: str | None = None):
    """Fetch items with prices from server API and cache locally."""
    init_db()

    page = 1
    all_items = []

    while True:
        result = await api_client.get_items(
            server=server, category=category, page=page,
        )
        if result is None:
            log.error("Failed to fetch items from server (page %d)", page)
            break

        items = result.get("items", [])
        if not items:
            break

        all_items.extend(items)
        total = result.get("total", 0)
        if len(all_items) >= total:
            break
        page += 1

    if not all_items:
        return []

    # Update local cache
    c = _conn()

    # Ensure price_cache table exists
    c.execute("""
        CREATE TABLE IF NOT EXISTS price_cache (
            item_id INTEGER NOT NULL,
            server TEXT NOT NULL,
            last_price INTEGER,
            median_7d INTEGER,
            last_updated TEXT,
            PRIMARY KEY (item_id, server)
        )
    """)

    for item in all_items:
        # Upsert item
        c.execute(
            "INSERT INTO items (id, name, category, detail_url) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
            "category=excluded.category, detail_url=excluded.detail_url",
            (item["id"], item["name"], item.get("category"), item.get("detail_url")),
        )

        # Cache price summary if available
        last_price = item.get("last_price")
        median_7d = item.get("median_7d")
        last_updated = item.get("last_updated")

        if last_price is not None or median_7d is not None:
            c.execute(
                "INSERT INTO price_cache (item_id, server, last_price, median_7d, last_updated) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(item_id, server) DO UPDATE SET "
                "last_price=excluded.last_price, median_7d=excluded.median_7d, "
                "last_updated=excluded.last_updated",
                (item["id"], server,
                 int(last_price) if last_price else None,
                 int(median_7d) if median_7d else None,
                 last_updated),
            )

    c.commit()
    log.info("Synced %d items from server", len(all_items))
    return all_items


def get_cached_items_with_prices(server: str, category: str | None = None):
    """Get items with cached price data from local DB."""
    init_db()
    c = _conn()

    # Ensure price_cache table exists
    c.execute("""
        CREATE TABLE IF NOT EXISTS price_cache (
            item_id INTEGER NOT NULL,
            server TEXT NOT NULL,
            last_price INTEGER,
            median_7d INTEGER,
            last_updated TEXT,
            PRIMARY KEY (item_id, server)
        )
    """)

    sql = (
        "SELECT i.id, i.name, i.category, "
        "pc.last_price, pc.median_7d, pc.last_updated "
        "FROM items i LEFT JOIN price_cache pc ON i.id = pc.item_id AND pc.server = ? "
    )
    params = [server]
    if category:
        sql += "WHERE i.category = ? "
        params.append(category)
    sql += "ORDER BY i.name"

    return [tuple(r) for r in c.execute(sql, params).fetchall()]
