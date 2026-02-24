"""Daily wiki scraper — fetches item catalog (NOT prices) from wiki.majestic-rp.ru."""

import logging
import re

import aiohttp

from ..database import upsert_items_bulk

log = logging.getLogger(__name__)

BASE = "https://wiki.majestic-rp.ru"
IMG_CDN = "https://cdn.majestic-files.net/public/master/static/img/inventory/items"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip()


def _parse_price(s: str) -> int:
    s = s.strip().replace("$", "").replace("\xa0", "").replace(" ", "")
    try:
        return int(s)
    except ValueError:
        return 0


async def fetch_items_list(session: aiohttp.ClientSession) -> list[dict]:
    """Parse all 10 pages of /ru/items?page=N. Returns item dicts."""
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

            divs = re.findall(r"<div[^>]*>([^<]+)</div>", inner)
            name = divs[1].strip() if len(divs) >= 2 else f"Item {item_id}"
            detail_url = f"/ru/items/{cat}/{item_id}"
            image_url = f"{IMG_CDN}/{item_id}.png"

            items.append({
                "id": item_id,
                "name": name,
                "category": cat,
                "detail_url": detail_url,
                "image_url": image_url,
            })

    log.info("Fetched %d items from wiki list pages", len(items))
    return items


async def check_has_min_price(
    session: aiohttp.ClientSession, detail_url: str,
) -> bool:
    """Check if item detail page has min_price > 0 on any server."""
    url = f"{BASE}{detail_url}"
    try:
        async with session.get(url, headers=_HEADERS) as resp:
            html = await resp.text()
    except Exception:
        return False

    for row_m in re.finditer(r"<tr>(.*?)</tr>", html, re.DOTALL):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row_m.group(1), re.DOTALL)
        if len(tds) < 6:
            continue
        server = _text(tds[0])
        if not server or server == "Сервер":
            continue
        min_price = _parse_price(_text(tds[4]))
        if min_price > 0:
            return True
    return False


async def scrape_wiki():
    """Main scraper entry point. Fetches item catalog, checks has_min_price, upserts to DB."""
    log.info("Starting daily wiki scrape")
    try:
        async with aiohttp.ClientSession() as session:
            items = await fetch_items_list(session)
            if not items:
                log.warning("No items found on wiki")
                return

            # Check has_min_price for each item (with concurrency limit)
            import asyncio
            sem = asyncio.Semaphore(10)

            async def _check_one(item: dict):
                async with sem:
                    item["has_min_price"] = await check_has_min_price(
                        session, item["detail_url"]
                    )

            await asyncio.gather(*[_check_one(i) for i in items])

            # Upsert all items
            await upsert_items_bulk(items)
            log.info("Wiki scrape complete: %d items upserted", len(items))

    except Exception:
        log.exception("Wiki scrape failed")
