"""Price scan automation — simplified sell bot that only reads prices.

For each item: click items tab → search → type name → OCR price → POST to server.
No creation/placement steps.
"""

import asyncio
import logging

from core import get_game_rect
from modules.input import tap_vk, type_text, _vk_down, _vk_up
from modules.game_interaction import (
    find_and_click,
    ocr_min_price,
    wait_active,
    clear_overlay,
)

log = logging.getLogger(__name__)


async def _wait(state, seconds=1.0):
    return await wait_active(state, seconds, "scan_active")


async def _run_scan(state):
    """Scan prices for all items in state.scan_items."""
    items = state.scan_items

    for i, (item_id, name) in enumerate(items):
        if not state.scan_active:
            break

        clear_overlay(state)
        state.game_rect = get_game_rect()

        # countdown before first item
        if i == 0:
            for sec in [3, 2, 1]:
                if not state.scan_active:
                    break
                state.scan_step = str(sec)
                if not await _wait(state):
                    break
            if not state.scan_active:
                break

        # 1. click "Предметы" tab
        state.scan_step = f"[{i+1}/{len(items)}] Предметы"
        await find_and_click(state, "items")
        if not await _wait(state):
            break

        # 2. click search field → Ctrl+A
        state.scan_step = f"[{i+1}/{len(items)}] Поиск"
        await find_and_click(state, "item_search")
        await asyncio.sleep(0.3)
        _vk_down(0x11)  # VK_CONTROL
        tap_vk(0x41)    # 'A'
        _vk_up(0x11)
        await asyncio.sleep(0.1)

        # 3. type item name
        state.scan_step = f"[{i+1}/{len(items)}] {name}"
        type_text(name)
        if not await _wait(state):
            break

        # 4. OCR price
        state.scan_step = f"[{i+1}/{len(items)}] OCR цены"
        price = await ocr_min_price(state)

        if price and state.api_client and state.is_authenticated:
            try:
                await state.api_client.submit_price(
                    item_id, state.current_server, price, "scan",
                )
                log.info("Scan: '%s' price=%d submitted", name, price)
            except Exception:
                log.exception("Scan: failed to submit price for '%s'", name)
        elif price:
            log.info("Scan: '%s' price=%d (not submitted — not authenticated)", name, price)
        else:
            log.info("Scan: '%s' price not detected", name)

        if not await _wait(state, 0.5):
            break

    clear_overlay(state)
    log.info("Scan cycle finished: %d items", len(items))


async def price_scan_loop(state):
    """Price scan main loop — runs in asyncio background thread."""
    log.info("Price scan loop started")

    while True:
        if not state.scan_active:
            await asyncio.sleep(0.2)
            continue

        # ensure frame provider
        if not state.frame_provider.running:
            state.frame_provider.start()
            for _ in range(20):
                await asyncio.sleep(0.1)
                if state.frame_provider.get_image() is not None:
                    break

        state.game_rect = get_game_rect()
        state.scan_step = "Запуск..."

        try:
            await _run_scan(state)
        except Exception:
            log.exception("Scan cycle error")

        state.scan_active = False
        state.scan_step = "done"
