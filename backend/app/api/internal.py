"""Internal endpoints for module lifecycle management."""
import logging
import os
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"])


def _get_tenant(request: Request) -> str:
    return request.headers.get("X-Tenant-ID", request.headers.get("NGSILD-Tenant", ""))


def _verify_internal_secret(request: Request) -> bool:
    secret = request.headers.get("X-Internal-Service-Secret", "")
    expected = os.getenv("INTERNAL_SERVICE_SECRET", "")
    if not expected:
        logger.warning("INTERNAL_SERVICE_SECRET not configured — setup-parcel will fail")
        return False
    return secret == expected


@router.post("/setup-parcel")
async def setup_parcel(request: Request, body: dict):
    """Activate field-operations module for a parcel.

    Called by entity-manager when user activates the module for a parcel.
    Authenticated by X-Internal-Service-Secret only — no JWT.
    """
    if not _verify_internal_secret(request):
        raise HTTPException(403, "Invalid internal service secret")

    tenant_id = _get_tenant(request)
    parcel_id = body.get("parcel_id")
    if not parcel_id:
        raise HTTPException(400, "parcel_id is required")

    logger.info(
        "Module field-operations activated for parcel %s (tenant %s)",
        parcel_id, tenant_id,
    )
    return {
        "status": "ok",
        "setup_status": "ok",
        "parcel_id": parcel_id,
        "module": "field-operations",
    }


@router.post("/deactivate-parcel")
async def deactivate_parcel(request: Request, body: dict):
    """Deactivate field-operations module for a parcel."""
    if not _verify_internal_secret(request):
        raise HTTPException(403, "Invalid internal service secret")

    tenant_id = _get_tenant(request)
    parcel_id = body.get("parcel_id")
    if not parcel_id:
        raise HTTPException(400, "parcel_id is required")

    logger.info(
        "Module field-operations deactivated for parcel %s (tenant %s)",
        parcel_id, tenant_id,
    )
    return {"status": "ok", "parcel_id": parcel_id}
