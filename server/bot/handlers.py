import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from ..database import upsert_user
from ..routers.app import get_latest_release

log = logging.getLogger(__name__)

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    await upsert_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    # Deep link (e.g. /start subscribe_fishing)
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1].startswith("subscribe_"):
        module_id = args[1].replace("subscribe_", "")
        from .payments import send_module_invoice
        await send_module_invoice(message.bot, message.chat.id, module_id)
        return

    # Latest release from GitHub
    rel = await get_latest_release()

    download_text = ""
    if rel and rel.get("download_url"):
        download_text = (
            f"\n\nMJ Port v{rel['version']}\n"
            f"Скачать: {rel['download_url']}"
        )

    await message.answer(
        f"Привет, {user.first_name}!\n\n"
        f"Это бот MJ Port для Majestic Multiplayer.\n"
        f"Скачайте приложение и войдите через Telegram.{download_text}"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Доступные команды:\n\n"
        "/start — Скачать приложение\n"
        "/help — Эта справка\n\n"
        "Для оформления подписки используйте приложение."
    )
