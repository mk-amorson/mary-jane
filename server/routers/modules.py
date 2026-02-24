from fastapi import APIRouter, Depends

from ..auth.middleware import get_optional_user
from ..database import get_active_subscriptions, get_modules

router = APIRouter(prefix="/modules", tags=["modules"])


@router.get("")
async def list_modules(user: dict | None = Depends(get_optional_user)):
    modules = await get_modules()

    if user:
        subs = await get_active_subscriptions(user["id"])
        active_module_ids = {s["module_id"] for s in subs}
    else:
        active_module_ids = set()

    result = []
    for m in modules:
        has_access = m["is_free"] or m["id"] in active_module_ids
        result.append({**m, "has_access": has_access})

    return {"modules": result}
