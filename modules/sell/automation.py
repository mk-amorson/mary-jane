"""Sell automation — asyncio loop (same pattern as fishing bot).

Runs in the background asyncio thread. UI sets state.sell_active=True
with sell_items/sell_offset, this loop picks it up.
"""

import asyncio
import logging

from core import get_game_rect
from modules.input import tap_vk, type_text, VK_BACK, _vk_down, _vk_up
from modules.game_interaction import (
    grab_frame,
    find_and_click,
    ocr_min_price,
    find_item_name_on_screen,
    wait_active,
    clear_overlay,
)

log = logging.getLogger(__name__)


async def _wait(state, seconds=1.0):
    return await wait_active(state, seconds, "sell_active")


# ── Main sell sequence ──

async def _run_sell(state):
    """Execute sell cycle for all items in state.sell_items."""
    items = state.sell_items
    offset = state.sell_offset

    for i, (item_id, name, qty) in enumerate(items):
        if not state.sell_active:
            break

        clear_overlay(state)
        state.game_rect = get_game_rect()

        # Check server price cache for optimization
        cached_price = None
        if state.api_client and state.is_authenticated:
            try:
                price_data = await state.api_client.get_price_latest(
                    item_id, state.current_server,
                )
                if price_data and price_data.get("last_updated"):
                    from datetime import datetime, timezone
                    last_str = price_data["last_updated"]
                    # If price is recent (<1 min), skip OCR
                    # Simple heuristic: just use the cached price
                    cached_price = price_data.get("last_price")
            except Exception:
                pass

        # countdown before first item
        if i == 0:
            for sec in [3, 2, 1]:
                if not state.sell_active:
                    break
                state.sell_step = str(sec)
                if not await _wait(state):
                    break
            if not state.sell_active:
                break

        if cached_price and cached_price > offset:
            # Skip OCR — use cached price
            sell_price = max(1, cached_price - offset)
            log.info("Sell: '%s' using cached price=%d sell_price=%d", name, cached_price, sell_price)
        else:
            # Full cycle: navigate to item, OCR price

            # 1. click "Предметы" tab
            state.sell_step = "Предметы"
            await find_and_click(state, "items")
            if not await _wait(state):
                break

            # 2. click search field → Ctrl+A → type name
            state.sell_step = "Поиск"
            await find_and_click(state, "item_search")
            await asyncio.sleep(0.3)
            _vk_down(0x11)  # VK_CONTROL
            tap_vk(0x41)    # 'A'
            _vk_up(0x11)
            await asyncio.sleep(0.1)

            # 3. type item name
            state.sell_step = f"Ввод: {name}"
            type_text(name)
            if not await _wait(state):
                break

            # 4. OCR min price
            state.sell_step = "Анализ цены"
            min_price = await ocr_min_price(state)
            sell_price = max(1, (min_price or 1) - offset)
            log.info("Sell: '%s' min_price=%s sell_price=%d", name, min_price, sell_price)

            # Submit price to server
            if min_price and state.api_client and state.is_authenticated:
                try:
                    await state.api_client.submit_price(
                        item_id, state.current_server, min_price, "sell",
                    )
                except Exception:
                    log.exception("Sell: failed to submit price")

            if not await _wait(state):
                break

        # 5. click "Создать"
        state.sell_step = "Создание"
        await find_and_click(state, "create")
        if not await _wait(state):
            break

        # 6. click item name on screen
        state.sell_step = "Выбор предмета"
        await find_item_name_on_screen(state, name)
        if not await _wait(state):
            break

        # 7. click quantity field
        state.sell_step = "Количество"
        await find_and_click(state, "item_count")
        if not await _wait(state):
            break

        # 8. clear quantity field
        state.sell_step = "Очистка"
        for _ in range(4):
            tap_vk(VK_BACK)
            await asyncio.sleep(0.05)
        if not await _wait(state, 0.5):
            break

        # 9. type quantity
        state.sell_step = "Ввод кол-ва"
        type_text(str(qty))
        if not await _wait(state):
            break

        # 10. click price field and type price
        state.sell_step = "Ввод цены"
        await find_and_click(state, "set_price")
        await asyncio.sleep(0.3)
        type_text(str(sell_price))
        if not await _wait(state):
            break

        # 11. click "Разместить"
        state.sell_step = "Размещение"
        await find_and_click(state, "place_order")
        if not await _wait(state):
            break

    clear_overlay(state)
    log.info("Sell cycle finished")


# ── Main loop (like fishing_bot_loop) ──

async def sell_bot_loop(state):
    """Sell bot main loop — runs in asyncio background thread."""
    log.info("Sell bot loop started")

    while True:
        if not state.sell_active:
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
        state.sell_step = "Запуск..."

        try:
            await _run_sell(state)
        except Exception:
            log.exception("Sell cycle error")

        state.sell_active = False
        state.sell_step = "done"
