from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import APIRouter, Request

from ..config import get_settings

router = APIRouter(tags=["webhook"])

# Set from main.py lifespan
_dp: Dispatcher | None = None
_bot: Bot | None = None


def set_dispatcher(dp: Dispatcher, bot: Bot):
    global _dp, _bot
    _dp = dp
    _bot = bot


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    if _dp is None or _bot is None:
        return {"ok": False}

    data = await request.json()
    update = Update.model_validate(data, context={"bot": _bot})
    await _dp.feed_update(_bot, update)
    return {"ok": True}
