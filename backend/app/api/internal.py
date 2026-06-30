"""Internal endpoints for module lifecycle management."""
import hmac
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


@router.post("/suggested-operation")
async def suggested_operation(request: Request, body: dict):
    """Receive a SAR-detected operation suggestion from vegetation-health.

    Auth: X-Internal-Service-Secret (hmac.compare_digest).
    Creates AgriParcelOperation with status="suggested" in Orion-LD.
    """
    secret = request.headers.get("X-Internal-Service-Secret", "")
    expected = os.getenv("INTERNAL_SERVICE_SECRET", "")
    if not expected or not hmac.compare_digest(secret, expected):
        raise HTTPException(401, "Invalid internal service secret")

    tenant_id = body.get("tenant_id", "")
    parcel_id = body.get("parcel_id", "")
    operation_type = body.get("operation_type", "")
    confidence = body.get("confidence", 0.0)
    sensing_date = body.get("sensing_date", "")
    delta_vv_db = body.get("delta_vv_db", 0.0)
    scene_id = body.get("scene_id", "")

    if not tenant_id or not parcel_id:
        raise HTTPException(400, "tenant_id and parcel_id required")
    if operation_type not in ("tillage", "harvest", "sowing"):
        raise HTTPException(400, f"Invalid operation_type: {operation_type}")

    from app.orion_ops import create_suggested_operation

    try:
        op = create_suggested_operation(
            tenant_id=tenant_id,
            parcel_id=parcel_id,
            operation_type=operation_type,
            confidence=confidence,
            delta_vv_db=delta_vv_db,
            sensing_date=sensing_date,
            scene_id=scene_id,
        )
        if op is None:
            raise HTTPException(409, "Operation already suggested for this parcel+date+type")
        return {"status": "suggested", "operation_id": op, "message": "Operation suggested for review"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to create suggested operation: %s", exc)
        raise HTTPException(500, "Internal error creating suggested operation")
