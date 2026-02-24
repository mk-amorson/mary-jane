import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.types import BufferedInputFile
from aiogram.filters import Command

from core import BOT_TOKEN

log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def set_state(state):
    """Inject AppState so handlers can use it."""
    dp["state"] = state
    state.bot = bot


@dp.startup()
async def on_startup():
    dp["state"].telegram_status = "connected"
    log.info("Bot connected")


@dp.shutdown()
async def on_shutdown():
    dp["state"].telegram_status = "off"
    log.info("Bot disconnected")


@dp.message(Command("screenshot"))
async def cmd_screenshot(message: types.Message):
    state = dp["state"]
    if not state.telegram_enabled:
        return
    state.chat_id = message.chat.id
    img_buf = state.frame_provider.ensure_running_and_grab()
    if img_buf is None:
        await message.reply("Игра не запущена.")
    else:
        photo = BufferedInputFile(img_buf.read(), filename="screenshot.png")
        await message.reply_photo(photo=photo)


async def telegram_manager(state):
    """Watch state.telegram_enabled and start/stop bot polling."""
    polling_task = None

    while True:
        await asyncio.sleep(0.5)

        if state.telegram_enabled and polling_task is None:
            state.telegram_status = "connecting"
            log.info("Starting bot polling...")
            polling_task = asyncio.create_task(
                dp.start_polling(bot, handle_signals=False, close_bot_session=False)
            )

        elif not state.telegram_enabled and polling_task is not None:
            log.info("Stopping bot polling...")
            await dp.stop_polling()
            try:
                await asyncio.wait_for(polling_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                polling_task.cancel()
            polling_task = None
            state.telegram_status = "off"

        elif polling_task is not None and polling_task.done():
            # polling ended unexpectedly
            exc = polling_task.exception() if not polling_task.cancelled() else None
            if exc:
                log.error("Bot polling failed: %s", exc)
            polling_task = None
            state.telegram_status = "off"
