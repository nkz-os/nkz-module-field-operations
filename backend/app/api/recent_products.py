"""GET /recent-products: names of the spraying products / fertilisers a holding used lately."""
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, Request

from ..services import recent_products as svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/field-operations", tags=["recent-products"])


@router.get("/recent-products")
async def get_recent_products(request: Request, kind: str = Query(default=""),
                              limit: str = Query(default="10")) -> dict:
    if kind not in svc.KINDS:
        raise HTTPException(status_code=400, detail={"code": "invalid_kind"})
    try:
        n = min(50, max(1, int(limit)))
    except ValueError:
        raise HTTPException(status_code=400, detail={"code": "invalid_limit"})
    tenant_id = request.state.tenant_id
    try:
        products = await asyncio.to_thread(svc.recent_products, tenant_id, kind, n)
    except Exception as exc:  # noqa: BLE001 - any broker failure is a 503, never a silent empty list
        logger.error("recent-products: query failed tenant=%s kind=%s: %s", tenant_id, kind, exc)
        raise HTTPException(status_code=503, detail={"code": "store_unavailable", "detail": str(exc)})
    return {"kind": kind, "products": products}
