import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth.middleware import get_current_user, get_optional_user
from ..database import get_active_subscriptions, get_modules

log = logging.getLogger(__name__)

router = APIRouter(prefix="/modules", tags=["modules"])


@router.get("")
async def list_modules(user: dict | None = Depends(get_optional_user)):
    modules = await get_modules()

    if user:
        subs = await get_active_subscriptions(user["id"])
        sub_map = {s["module_id"]: s for s in subs}
    else:
        sub_map = {}

    result = []
    for m in modules:
        sub = sub_map.get(m["id"])
        has_access = m["is_free"] or sub is not None
        entry = {**m, "has_access": has_access}
        if sub:
            entry["expires_at"] = sub.get("expires_at")
        result.append(entry)

    return {"modules": result}


@router.post("/{module_id}/subscribe")
async def request_subscribe(
    module_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Send a Telegram Stars invoice to the user's chat."""
    bot = getattr(request.app.state, "bot", None)
    if bot is None:
        raise HTTPException(503, "Bot not available")

    telegram_id = user.get("telegram_id")
    if not telegram_id:
        raise HTTPException(400, "No telegram_id on user")

    from ..bot.payments import send_module_invoice
    try:
        await send_module_invoice(bot, telegram_id, module_id)
    except Exception:
        log.exception("Failed to send invoice to %s", telegram_id)
        raise HTTPException(500, "Failed to send invoice")

    return {"ok": True}
