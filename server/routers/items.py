from fastapi import APIRouter, Query

from ..database import get_items

router = APIRouter(prefix="/items", tags=["items"])


@router.get("")
async def list_items(
    server: str | None = Query(None),
    category: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
):
    items, total = await get_items(
        server=server,
        category=category,
        search=search,
        page=page,
        per_page=per_page,
    )
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
    }
