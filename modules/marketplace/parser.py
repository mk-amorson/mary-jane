import re
import time
import asyncio
import logging

import aiohttp

log = logging.getLogger(__name__)

BASE = "https://wiki.majestic-rp.ru"
IMG_CDN = "https://cdn.majestic-files.net/public/master/static/img/inventory/items"

_HEADERS = {"User-Agent": "Mozilla/5.0"}

SERVERS = [
    "New York", "Detroit", "Chicago", "San Francisco", "Atlanta",
    "San Diego", "Los Angeles", "Miami", "Las Vegas", "Washington",
    "Dallas", "Boston", "Houston", "Seattle", "Phoenix",
    "Denver", "Portland", "Berlin", "Warsaw",
]

# (slug, Russian name) — "" means "all"
CATEGORIES = [
    ("", "Все"),
    ("food", "Продукты"),
    ("tool", "Инструменты"),
    ("fish", "Рыба"),
    ("equipment", "Оборудование"),
    ("alcohol", "Алкоголь"),
    ("ammunition", "Амуниция"),
    ("medical", "Медицина"),
    ("autoParts", "Автозапчасти"),
    ("misc", "Прочее"),
    ("consumables", "Расходники"),
    ("facilities", "Инфраструктура"),
    ("documents", "Документы"),
    ("books", "Книги"),
    ("personals", "Личные вещи"),
    ("products", "Продукция"),
    ("materials", "Материалы"),
    ("clothes", "Одежда"),
    ("rubbish", "Мусор"),
    ("agriculture", "С/х"),
    ("drugs", "Стафф"),
    ("ingredients", "Ингредиенты"),
    ("armor", "Броня"),
    ("others", "Разное"),
]


def _text(html):
    """Strip HTML tags and return clean text."""
    return re.sub(r"<[^>]+>", "", html).strip()


def _parse_price(s):
    """Parse price string like '$1 174' or '6 546' to int."""
    s = s.strip().replace("$", "").replace("\xa0", "").replace(" ", "")
    try:
        return int(s)
    except ValueError:
        return 0


async def fetch_items_list(session):
    """Parse all 10 pages of /ru/items?page=N.

    Returns list of (id, name, category, detail_url).
    """
    items = []
    seen = set()

    for page in range(1, 11):
        url = f"{BASE}/ru/items?page={page}"
        try:
            async with session.get(url, headers=_HEADERS) as resp:
                html = await resp.text()
        except Exception:
            log.exception("Failed to fetch items page %d", page)
            continue

        # <a ... href="/ru/items/cat/id">...<div>Category</div><div>Name</div>...</a>
        for m in re.finditer(
            r'<a[^>]*href="/ru/items/(\w+)/(\d+)"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        ):
            cat, item_id_str, inner = m.group(1), m.group(2), m.group(3)
            item_id = int(item_id_str)
            if item_id in seen:
                continue
            seen.add(item_id)

            # Name is the second <div> text inside the <a>
            divs = re.findall(r"<div[^>]*>([^<]+)</div>", inner)
            name = divs[1].strip() if len(divs) >= 2 else f"Item {item_id}"
            detail_url = f"/ru/items/{cat}/{item_id}"
            items.append((item_id, name, cat, detail_url))

    log.info("Fetched %d items from list pages", len(items))
    return items


async def fetch_item_prices(session, detail_url):
    """Parse detail page price table.

    Returns list of (server, in_sale, sold, avg_price, min_price, max_price).
    """
    url = f"{BASE}{detail_url}"
    try:
        async with session.get(url, headers=_HEADERS) as resp:
            html = await resp.text()
    except Exception:
        log.exception("Failed to fetch %s", detail_url)
        return []

    prices = []
    for row_m in re.finditer(r"<tr>(.*?)</tr>", html, re.DOTALL):
        row_html = row_m.group(1)
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL)
        if len(tds) < 6:
            continue

        server = _text(tds[0])
        if not server or server == "\u0421\u0435\u0440\u0432\u0435\u0440":
            continue

        try:
            prices.append((
                server,
                _parse_price(_text(tds[1])),
                _parse_price(_text(tds[2])),
                _parse_price(_text(tds[3])),
                _parse_price(_text(tds[4])),
                _parse_price(_text(tds[5])),
            ))
        except Exception:
            continue

    return prices


async def parse_all(state):
    """Phase 1: fetch item list.  Phase 2: fetch prices (Semaphore 20)."""
    from .database import init_db, upsert_item, upsert_prices

    state.marketplace_parsing = True
    state.marketplace_error = None
    state.marketplace_done = 0
    state.marketplace_total = 0

    try:
        init_db()

        async with aiohttp.ClientSession() as session:
            # Phase 1 — list
            items = await fetch_items_list(session)
            if not items:
                state.marketplace_error = "No items found"
                return

            state.marketplace_total = len(items)
            state.marketplace_start_time = time.monotonic()

            for item_id, name, cat, url in items:
                upsert_item(item_id, name, cat, url)

            # Phase 2 — prices
            sem = asyncio.Semaphore(20)

            async def _fetch_one(item_id, url):
                async with sem:
                    prices = await fetch_item_prices(session, url)
                    if prices:
                        upsert_prices(item_id, prices)
                    state.marketplace_done += 1

            await asyncio.gather(
                *[_fetch_one(iid, url) for iid, _, _, url in items]
            )
    except Exception as e:
        log.exception("Marketplace parse failed")
        state.marketplace_error = str(e)
    finally:
        state.marketplace_parsing = False


async def parse_selected(state, item_ids):
    """Fetch prices only for given item IDs."""
    from .database import init_db, upsert_prices

    state.marketplace_parsing = True
    state.marketplace_error = None
    state.marketplace_done = 0
    state.marketplace_total = len(item_ids)
    state.marketplace_start_time = time.monotonic()

    try:
        init_db()
        # look up detail URLs from DB
        from .database import _conn
        c = _conn()
        rows = c.execute(
            "SELECT id, detail_url FROM items WHERE id IN ({})".format(
                ",".join("?" * len(item_ids))
            ),
            item_ids,
        ).fetchall()
        url_map = {r[0]: r[1] for r in rows}

        async with aiohttp.ClientSession() as session:
            sem = asyncio.Semaphore(20)

            async def _fetch_one(item_id, url):
                async with sem:
                    prices = await fetch_item_prices(session, url)
                    if prices:
                        upsert_prices(item_id, prices)
                    state.marketplace_done += 1

            await asyncio.gather(
                *[_fetch_one(iid, url_map[iid]) for iid in item_ids if iid in url_map]
            )
    except Exception as e:
        log.exception("Marketplace parse_selected failed")
        state.marketplace_error = str(e)
    finally:
        state.marketplace_parsing = False
