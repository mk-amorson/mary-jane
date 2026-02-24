import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

import jwt

from ..config import get_settings


def validate_telegram_data(data: dict) -> bool:
    """Validate hash from Telegram Login Widget."""
    settings = get_settings()
    check_hash = data.pop("hash", None)
    if not check_hash:
        return False

    # data must not be older than 1 day
    auth_date = data.get("auth_date")
    if auth_date and (time.time() - int(auth_date)) > 86400:
        data["hash"] = check_hash
        return False

    secret = hashlib.sha256(settings.bot_token.encode()).digest()
    check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(data.items()) if v is not None
    )
    computed = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()

    data["hash"] = check_hash  # restore
    return hmac.compare_digest(computed, check_hash)


def create_access_token(user_id: int, telegram_id: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "telegram_id": telegram_id,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "iat": now,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: int, telegram_id: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "telegram_id": telegram_id,
        "exp": now + timedelta(days=settings.refresh_token_expire_days),
        "iat": now,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    settings = get_settings()
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return None
