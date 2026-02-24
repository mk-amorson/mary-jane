from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth.middleware import get_current_user
from ..database import add_price, get_median_for_validation, get_price_latest

router = APIRouter(prefix="/prices", tags=["prices"])


class PriceSubmit(BaseModel):
    item_id: int
    server_name: str
    price: int
    source: str  # 'sell' | 'scan'


@router.post("")
async def submit_price(
    body: PriceSubmit,
    user: dict = Depends(get_current_user),
):
    if body.source not in ("sell", "scan"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid source")
    if body.price <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Price must be > 0")

    # validate against median (anti-garbage OCR)
    median = await get_median_for_validation(body.item_id, body.server_name)
    if median is not None and median > 0:
        ratio = body.price / median
        if ratio > 3.0 or ratio < 0.3:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Price {body.price} too far from median {median} (ratio {ratio:.1f})",
            )

    result = await add_price(
        item_id=body.item_id,
        server_name=body.server_name,
        price=body.price,
        user_id=user["id"],
        source=body.source,
    )
    return {"ok": True, "price": result}


@router.get("/{item_id}/latest")
async def price_latest(item_id: int, server: str):
    summary = await get_price_latest(item_id, server)
    if summary is None:
        return {"item_id": item_id, "server": server, "last_price": None, "median_7d": None, "last_updated": None}
    return summary
