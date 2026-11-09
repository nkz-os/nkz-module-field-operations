"""Internal endpoints for module lifecycle management."""
import hmac
import logging
import os
import re
from datetime import date

import requests
from fastapi import APIRouter, HTTPException, Request, Response
from nkz_platform_sdk.notify_auth import accept_master_from_env, verify_notification

from ..services import weekly_report
from ..services.crop_cycles_runtime import enqueue
from ..services.crop_cycles_writer import parcels_in_notification

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


@router.post("/notify/crop-cycles", status_code=204)
async def notify_crop_cycles(request: Request):
    """Orion: AgriCrop / AgriParcelOperation changed. Queue the parcels; always 204, no body."""
    if not verify_notification(
        request.headers, secret=os.getenv("INTERNAL_SERVICE_SECRET", ""), accept_master=accept_master_from_env()
    ):
        raise HTTPException(401, "Unauthorized")
    tenant_id = request.headers.get("NGSILD-Tenant") or request.headers.get("Fiware-Service")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — a malformed delivery carries no parcels
        body = {}
    data = body.get("data") if isinstance(body, dict) else None
    entities = [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    enqueue(tenant_id, parcels_in_notification(entities))
    return Response(status_code=204)


@router.post("/setup-parcel")
async def setup_parcel(request: Request, body: dict):
    """Activate field-operations module for a parcel.

    Called by entity-manager when user activates the module for a parcel.
    Authenticated by X-Internal-Service-Secret only — no JWT.
    """
    if not _verify_internal_secret(request):
        raise HTTPException(403, "Invalid internal service secret")

    # entity-manager sends the tenant in the body; the header is a fallback for direct calls.
    tenant_id = body.get("tenant_id") or _get_tenant(request)
    parcel_id = body.get("parcel_id")
    if not parcel_id:
        raise HTTPException(400, "parcel_id is required")

    logger.info(
        "Module field-operations %s for parcel %s (tenant %s)",
        body.get("action") or "activate", parcel_id, tenant_id,
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


_TENANT_RE = re.compile(r"^[a-z0-9_-]+$")


@router.get("/weekly-report")
def weekly_report_contribution(request: Request, tenant_id: str = "", week_start: str = ""):
    """Pending planned operations for the tenant's weekly report (contract v1).

    Auth: X-Internal-Service-Secret (hmac.compare_digest), fail-closed. An Orion
    failure answers 502 so an outage never reads as "nothing pending".
    """
    secret = request.headers.get("X-Internal-Service-Secret", "")
    expected = os.getenv("INTERNAL_SERVICE_SECRET", "")
    if not expected or not hmac.compare_digest(secret.encode(), expected.encode()):
        raise HTTPException(401, "Invalid internal service secret")
    if not _TENANT_RE.match(tenant_id):
        raise HTTPException(400, "tenant_id is required and must match ^[a-z0-9_-]+$")
    try:
        monday = date.fromisoformat(week_start)
    except ValueError:
        raise HTTPException(400, "week_start must be YYYY-MM-DD")
    if monday.weekday() != 0:
        raise HTTPException(400, "week_start must be a Monday")
    try:
        return weekly_report.build(tenant_id, monday)
    except (RuntimeError, requests.RequestException) as exc:  # Orion-LD error or network failure
        logger.error("weekly-report: Orion read failed tenant=%s: %s", tenant_id, exc)
        raise HTTPException(502, "Orion-LD unavailable")
    except Exception:  # noqa: BLE001 — a code bug is a 500, never a 200 with an empty list
        logger.exception("weekly-report: unexpected error tenant=%s", tenant_id)
        raise HTTPException(500, "Internal error")
