"""API routes for AgriParcelOperation management."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..config import VALID_OPERATION_TYPES, VALID_STATUSES
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
