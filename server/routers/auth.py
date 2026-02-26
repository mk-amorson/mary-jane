from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..auth.middleware import get_current_user
from ..auth.telegram import (
    create_access_token,
    create_refresh_token,
    decode_token,
    validate_telegram_data,
)
from ..config import get_settings
from ..database import get_active_subscriptions, get_user_by_id, upsert_user

router = APIRouter(prefix="/auth", tags=["auth"])


class TelegramAuthRequest(BaseModel):
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/telegram", response_model=TokenResponse)
async def auth_telegram(body: TelegramAuthRequest):
    data = body.model_dump()
    telegram_id = data["id"]
    if not validate_telegram_data(data):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Telegram auth")

    user = await upsert_user(
        telegram_id=telegram_id,
        username=body.username,
        first_name=body.first_name,
        photo_url=body.photo_url,
    )
    return TokenResponse(
        access_token=create_access_token(user["id"], telegram_id),
        refresh_token=create_refresh_token(user["id"], telegram_id),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(body: RefreshRequest):
    payload = decode_token(body.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    user_id = int(payload["sub"])
    user = await get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    if user.get("is_banned"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account banned")

    return TokenResponse(
        access_token=create_access_token(user_id, user["telegram_id"]),
        refresh_token=create_refresh_token(user_id, user["telegram_id"]),
    )


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    subs = await get_active_subscriptions(user["id"])
    return {
        "user": user,
        "subscriptions": subs,
    }


@router.get("/login-page", response_class=HTMLResponse)
async def login_page(redirect: str, request: Request):
    bot_username = getattr(request.app.state, "bot_username", "bot")
    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>MJ Port — Авторизация</title>
<style>
  body {{
    background: #1c1c20; color: #c8c8c8; font-family: sans-serif;
    display: flex; justify-content: center; align-items: center;
    height: 100vh; margin: 0;
  }}
  .container {{ text-align: center; }}
  h1 {{ font-size: 24px; margin-bottom: 20px; }}
</style>
</head><body>
<div class="container">
  <h1>MJ Port — Войти через Telegram</h1>
  <script async src="https://telegram.org/js/telegram-widget.js?22"
    data-telegram-login="{bot_username}"
    data-size="large"
    data-auth-url="{redirect}"
    data-request-access="write">
  </script>
</div>
</body></html>"""
    return HTMLResponse(html)
