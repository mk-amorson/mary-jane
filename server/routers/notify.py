from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth.middleware import get_current_user

router = APIRouter(prefix="/notify", tags=["notify"])

# Bot instance set from main.py lifespan
_bot = None


def set_bot(bot):
    global _bot
    _bot = bot


class QueueNotification(BaseModel):
    position: int
    threshold: int


@router.post("/queue")
async def notify_queue(
    body: QueueNotification,
    user: dict = Depends(get_current_user),
):
    if _bot is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Bot not initialized"
        )

    chat_id = user.get("telegram_id")
    if not chat_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No Telegram ID")

    text = (
        f"🎮 Очередь: позиция {body.position}\n"
        f"Порог: {body.threshold}\n"
        f"Скоро ваша очередь!"
    )
    try:
        await _bot.send_message(chat_id, text)
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Telegram error: {e}")

    return {"ok": True}
