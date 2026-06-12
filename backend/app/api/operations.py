"""API routes for AgriParcelOperation management."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from ..config import VALID_OPERATION_TYPES, VALID_STATUSES
from ..services.photo_service import upload_label_photo, get_label_photo
from ..services.work_order_service import create_external_work_order
from ..state_machine import can_transition, validate_completion_fields
from ..orion_ops import (
    create_operation, get_entity, update_entity_attrs,
    start_operation, complete_operation,
    enrich_from_isobus, query_operations, extrapolate_to_full_parcel,
)

router = APIRouter(prefix="/api/field-operations", tags=["field-operations"])


def _get_tenant(request: Request) -> str:
    return request.headers.get("X-Tenant-ID", request.headers.get("NGSILD-Tenant", ""))


def _get_roles(request: Request) -> list:
    raw = request.headers.get("X-User-Roles", "")
    return [r.strip() for r in raw.split(",") if r.strip()]


def _resolve_actor(roles: list) -> str:
    if "tenant_admin" in roles:
        return "tenant_admin"
    if "field_manager" in roles:
        return "field_manager"
    return "user"


def _get_or_404(tenant_id: str, operation_id: str) -> dict:
    entity = get_entity(tenant_id, operation_id)
    if not entity:
        raise HTTPException(404, f"Operation not found: {operation_id}")
    return entity


@router.get("/operations")
async def list_operations(
    request: Request,
    parcel_id: str = Query(None),
    operation_type: str = Query(None),
    status: str = Query(None),
    work_order: str = Query(None),
    limit: int = Query(100),
):
    tenant_id = _get_tenant(request)
    if operation_type and operation_type not in VALID_OPERATION_TYPES:
        raise HTTPException(400, f"Invalid operationType: {operation_type}")
    if status and status not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid status: {status}")
    results = query_operations(
        tenant_id, parcel_id=parcel_id, operation_type=operation_type,
        status=status, work_order=work_order, limit=limit,
    )
    return {"operations": results, "count": len(results)}


@router.post("/operations")
async def create_field_operation(request: Request, body: dict):
    tenant_id = _get_tenant(request)
    required = ["parcel_id", "operation_type", "work_order", "operator"]
    for field in required:
        if field not in body:
            raise HTTPException(400, f"Missing required field: {field}")

    entity = create_operation(
        tenant_id,
        parcel_id=body["parcel_id"],
        operation_type=body["operation_type"],
        work_order=body["work_order"],
        operator=body["operator"],
        data_source=body.get("data_source", "manual"),
        **{k: v for k, v in body.items() if k not in required + ["data_source"]},
    )
    return entity


@router.post("/work-orders")
async def create_work_order(request: Request, body: dict):
    """Generic API endpoint for external work orders.

    Used by Odoo bridge, mobile app, or any external system.
    Creates an AgriParcelOperation with status=issued for review.
    """
    tenant_id = _get_tenant(request)

    required = ["parcel_id", "operation_type", "work_order", "operator"]
    for field in required:
        if field not in body:
            raise HTTPException(400, f"Missing required field: {field}")

    try:
        entity = create_external_work_order(
            tenant_id,
            parcel_id=body["parcel_id"],
            operation_type=body["operation_type"],
            work_order=body["work_order"],
            operator=body["operator"],
            source=body.get("source", "api"),
            external_ref=body.get("external_ref"),
            planned_date=body.get("planned_date"),
            assigned_to=body.get("assigned_to"),
            **{k: v for k, v in body.items()
               if k not in required + ["source", "external_ref", "planned_date", "assigned_to"]},
        )
        return entity
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/operations/{operation_id}")
async def get_field_operation(operation_id: str, request: Request):
    tenant_id = _get_tenant(request)
    return _get_or_404(tenant_id, operation_id)


@router.post("/operations/{operation_id}/start")
async def api_start_operation(operation_id: str, request: Request):
    tenant_id = _get_tenant(request)
    entity = _get_or_404(tenant_id, operation_id)
    current_status = entity.get("status", {}).get("value", "")
    actor_role = _resolve_actor(_get_roles(request))
    result = can_transition(current_status, "incomplete", actor_role)
    if not result.allowed:
        raise HTTPException(403, result.reason)
    return start_operation(tenant_id, operation_id)


@router.post("/operations/{operation_id}/complete")
async def api_complete_operation(operation_id: str, request: Request, body: dict):
    tenant_id = _get_tenant(request)
    entity = _get_or_404(tenant_id, operation_id)
    current_status = entity.get("status", {}).get("value", "")
    op_type = entity.get("operationType", {}).get("value", "")
    actor_role = _resolve_actor(_get_roles(request))
    result = can_transition(current_status, "completed", actor_role)
    if not result.allowed:
        raise HTTPException(403, result.reason)

    missing = validate_completion_fields(op_type, entity)
    for field in list(missing):
        if field in body:
            missing.remove(field)
    if missing:
        raise HTTPException(400, f"Cannot complete: missing required fields: {missing}")

    return complete_operation(tenant_id, operation_id, extra_attrs=body)


@router.post("/operations/{operation_id}/cancel")
async def api_cancel_operation(operation_id: str, request: Request, body: dict):
    tenant_id = _get_tenant(request)
    entity = _get_or_404(tenant_id, operation_id)
    current_status = entity.get("status", {}).get("value", "")
    actor_role = _resolve_actor(_get_roles(request))
    result = can_transition(current_status, "cancelled", actor_role)
    if not result.allowed:
        raise HTTPException(403, result.reason)

    reason = body.get("cancellationReason", "")
    if not reason:
        raise HTTPException(400, "cancellationReason is required")

    update = {
        "status": {"type": "Property", "value": "cancelled"},
        "cancellationReason": {"type": "Property", "value": reason},
    }
    update_entity_attrs(tenant_id, operation_id, update)
    return {"status": "cancelled", "operation_id": operation_id}


@router.post("/operations/{operation_id}/isobus-data")
async def api_isobus_enrich(operation_id: str, request: Request, body: dict):
    """Receive ISOBUS telemetry for an ongoing operation. Auto-starts if still planned."""
    tenant_id = _get_tenant(request)
    entity = _get_or_404(tenant_id, operation_id)
    status = entity.get("status", {}).get("value", "")
    if status not in ("incomplete", "planned"):
        raise HTTPException(400, f"Cannot enrich operation with status '{status}'")
    if status == "planned":
        start_operation(tenant_id, operation_id)
    return enrich_from_isobus(tenant_id, operation_id, body)


@router.post("/operations/{operation_id}/label-photo")
def api_upload_label_photo(
    operation_id: str,
    request: Request,
    label_photo: UploadFile = File(...),
):
    """Upload a label/evidence photo for an operation."""
    tenant_id = _get_tenant(request)
    _get_or_404(tenant_id, operation_id)

    file_data = label_photo.read()
    try:
        url = upload_label_photo(
            tenant_id, operation_id, file_data,
            label_photo.filename or "photo.jpg",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    update_entity_attrs(tenant_id, operation_id, {
        "labelPhoto": {
            "type": "Property",
            "value": {
                "url": url,
                "uploadedAt": datetime.now(timezone.utc).isoformat(),
            },
        }
    })

    return {"url": url}


@router.get("/photos/{path:path}")
async def serve_label_photo(path: str, request: Request):
    """Serve a label photo from MinIO.

    The path matches the object_key structure:
    field-operations/{tenant_id}/{op_short}/label_{uuid}.{ext}
    """
    tenant_id = _get_tenant(request)

    parts = path.split("/")
    if len(parts) < 3 or parts[0] != "field-operations" or parts[1] != tenant_id:
        raise HTTPException(403, "Access denied")

    try:
        data, content_type = get_label_photo(path)
        return Response(content=data, media_type=content_type)
    except FileNotFoundError:
        raise HTTPException(404, "Photo not found")


@router.post("/operations/{operation_id}/extrapolate")
async def api_extrapolate(operation_id: str, request: Request, body: dict):
    tenant_id = _get_tenant(request)
    actor_role = _resolve_actor(_get_roles(request))
    if actor_role not in ("field_manager", "tenant_admin"):
        raise HTTPException(403, "Only field_manager or tenant_admin can extrapolate")

    parcel_area_ha = body.get("parcel_area_ha")
    if not parcel_area_ha:
        raise HTTPException(400, "parcel_area_ha is required")

    return extrapolate_to_full_parcel(tenant_id, operation_id, float(parcel_area_ha))
