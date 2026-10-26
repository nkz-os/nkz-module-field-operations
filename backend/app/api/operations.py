"""API routes for AgriParcelOperation management."""
import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from nkz_platform_sdk.crop_timeline import local_today

from ..services import irrigation_bridge
from ..config import VALID_OPERATION_TYPES, VALID_STATUSES
from ..services.photo_service import upload_label_photo, get_label_photo
from ..services.work_order_service import create_external_work_order
from ..state_machine import SENSOR_REVOKE_ACTORS, can_transition, validate_completion_fields, validate_sowing_method
from ..orion_ops import (
    create_operation, get_entity, update_entity_attrs,
    start_operation, complete_operation,
    enrich_from_isobus, query_operations, extrapolate_to_full_parcel,
)
from ..services.pesticide_validation import (
    enforce_spraying_validation,
    validate_spraying_product,
)
from ..fertilizer_composition import CompositionError, normalize_composition

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/field-operations", tags=["field-operations"])


def _get_tenant(request: Request) -> str:
    return request.headers.get("X-Tenant-ID", request.headers.get("NGSILD-Tenant", ""))


def _get_roles(request: Request) -> list:
    raw = request.headers.get("X-User-Roles", "")
    return [r.strip() for r in raw.split(",") if r.strip()]


def _get_user_id(request: Request) -> str:
    return request.headers.get("X-User-ID", "field-operations")


def _today(parcel: dict) -> date:
    return local_today(parcel)


def _unprocessable(code: str, detail: str):
    raise HTTPException(status_code=422, detail={"code": code, "detail": detail})


def _day_of(prop) -> date | None:
    """The calendar day of a stored DateTime property, or None when absent or unreadable."""
    value = prop.get("value") if isinstance(prop, dict) else prop
    if isinstance(value, dict):
        value = value.get("@value")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _pesticide_422(detail: str):
    raise HTTPException(
        status_code=422,
        detail={"code": "pesticide_not_authorized", "detail": detail},
    )


def _composition_or_422(operation_type: str, body: dict, stored: dict | None = None) -> dict:
    try:
        return normalize_composition(operation_type, body, stored)
    except CompositionError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_fertilizer_composition", "detail": str(exc)},
        )


# Platform (Keycloak realm) roles, plus the module's legacy names.
SENSOR_OVERLAP_CHOICES = ("keep_both", "replace_sensor")
_TENANT_ADMIN_ROLES = {"TenantAdmin", "PlatformAdmin", "tenant_admin"}
_FIELD_MANAGER_ROLES = {"TechnicalConsultant", "field_manager"}


def _resolve_actor(roles: list) -> str:
    if _TENANT_ADMIN_ROLES.intersection(roles):
        return "tenant_admin"
    if _FIELD_MANAGER_ROLES.intersection(roles):
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


@router.get("/validate-pesticide")
async def validate_pesticide(
    request: Request,
    parcel_id: str = Query(...),
    product_name: str = Query(...),
):
    """Pre-check spraying product authorization (for UI badges in P2)."""
    tenant_id = _get_tenant(request)
    result = validate_spraying_product(
        tenant_id, parcel_id, product_name, _get_user_id(request),
    )
    return {
        "status": result.status,
        "detail": result.detail,
        "crop_eppo": result.crop_eppo,
        "product_name": result.product_name,
        "authorized": result.status == "authorized",
    }


@router.post("/operations")
async def create_field_operation(request: Request, body: dict):
    tenant_id = _get_tenant(request)
    required = ["parcel_id", "operation_type", "work_order", "operator"]
    for field in required:
        if field not in body:
            raise HTTPException(400, f"Missing required field: {field}")
    error = validate_sowing_method(body["operation_type"], body)
    if error:
        raise HTTPException(400, error)
    body = _composition_or_422(body["operation_type"], body)

    try:
        enforce_spraying_validation(
            tenant_id,
            body["parcel_id"],
            body["operation_type"],
            body,
            _get_user_id(request),
        )
    except ValueError as exc:
        _pesticide_422(str(exc))

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
    error = validate_sowing_method(body["operation_type"], body)
    if error:
        raise HTTPException(400, error)
    body = _composition_or_422(body["operation_type"], body)

    try:
        enforce_spraying_validation(
            tenant_id,
            body["parcel_id"],
            body["operation_type"],
            body,
            _get_user_id(request),
        )
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
        msg = str(e)
        if "not authorized" in msg.lower():
            _pesticide_422(msg)
        raise HTTPException(400, msg)


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
    body = dict(body)
    completed_on = body.pop("completedOn", None)
    overlap = body.pop("sensorOverlap", None)
    if overlap is not None and overlap not in SENSOR_OVERLAP_CHOICES:
        _unprocessable("invalid_sensor_overlap", "sensorOverlap must be keep_both or replace_sensor")
    error = validate_sowing_method(op_type, body)
    if error:
        raise HTTPException(400, error)
    body = _composition_or_422(op_type, body, stored=entity)

    link = entity.get("hasAgriParcel") or entity.get("refAgriParcel") or {}
    parcel_ref = link.get("object", "") if isinstance(link, dict) else ""
    ended_at = started_at = None
    check_meter = op_type == "irrigation" and _prop_val(entity.get("dataSource")) != "sensor" and bool(parcel_ref)
    parcel = None
    if completed_on not in (None, "") or check_meter:
        parcel = get_entity(tenant_id, parcel_ref) if parcel_ref else None
        if not parcel:
            logger.warning(
                "complete: parcel not resolved, using UTC today tenant=%s operation=%s parcel=%s",
                tenant_id, operation_id, parcel_ref or "-",
            )
    day = None
    if completed_on not in (None, ""):
        try:
            day = date.fromisoformat(str(completed_on))
        except ValueError:
            _unprocessable("invalid_date", "completedOn must be YYYY-MM-DD")
        if day > _today(parcel or {}):
            _unprocessable("future_date", "completedOn cannot be in the future")
        ended_at = f"{day.isoformat()}T12:00:00Z"
        started_day = _day_of(entity.get("startedAt"))
        if started_day is not None and started_day > day:
            started_at = ended_at

    missing = validate_completion_fields(op_type, entity)
    for field in list(missing):
        if field in body:
            missing.remove(field)
    if missing:
        raise HTTPException(400, f"Cannot complete: missing required fields: {missing}")

    merged = {
        "productName": _prop_val(entity.get("productName")),
        "productRate": _prop_val(entity.get("productRate")),
        **body,
    }
    try:
        enforce_spraying_validation(
            tenant_id, parcel_ref, op_type, merged, _get_user_id(request),
        )
    except ValueError as exc:
        _pesticide_422(str(exc))

    raw_attrs = None
    if check_meter:
        sensor_op = _sensor_op_of_day(tenant_id, parcel_ref, day or _today(parcel or {}))
        if sensor_op is not None:
            sensor_id, sensor_entity, sensor_day = sensor_op
            actor = _resolve_actor(_get_roles(request))
            if overlap is None:
                raise HTTPException(409, {
                    "code": "sensor_irrigation_exists",
                    "detail": "A water meter already recorded irrigation on this day",
                    "sensorOperationId": sensor_id,
                    "sensorWaterPerHectare": _prop_val(sensor_entity.get("waterPerHectare")),
                    "day": sensor_day.isoformat(),
                })
            if overlap == "replace_sensor":
                if actor not in SENSOR_REVOKE_ACTORS:
                    raise HTTPException(403, "Only a technical consultant or a tenant admin can replace sensor operations")
                update_entity_attrs(tenant_id, sensor_id, _sensor_cancel_update(
                    sensor_entity, _get_user_id(request), "replaced by a manual record",
                ))
            else:
                raw_attrs = {
                    "possibleDuplicateOf": {"type": "Relationship", "object": sensor_id},
                    "duplicateReview": {"type": "Property", "value": "keep_both"},
                }

    return complete_operation(
        tenant_id, operation_id, ended_at=ended_at, started_at=started_at, extra_attrs=body,
        **({"raw_attrs": raw_attrs} if raw_attrs else {}),
    )


def _sensor_op_of_day(tenant_id: str, parcel_ref: str, day: date):
    """(id, entity, day) of the completed water-meter operation of that parcel and day, or None."""
    sensor_id = irrigation_bridge.operation_id(tenant_id, parcel_ref, day)
    entity = get_entity(tenant_id, sensor_id)
    if entity and _prop_val(entity.get("status")) == "completed":
        return sensor_id, entity, day
    return None


def _prop_val(prop: dict | None):
    if not isinstance(prop, dict):
        return None
    return prop.get("value")


def _sensor_cancel_update(entity: dict, user_id: str, reason: str) -> dict:
    """Attributes that revoke a completed sensor operation; the entry's author keeps the bridge away."""
    return {
        "status": {"type": "Property", "value": "cancelled"},
        "cancellationReason": {"type": "Property", "value": reason},
        "modificationLog": _log_with(entity, {
            "field": "status", "old": "completed", "new": "cancelled",
            "by": user_id, "at": datetime.now(timezone.utc).isoformat(),
            "method": "manual_cancellation", "reason": reason,
        }),
    }


def _log_with(entity: dict, entry: dict) -> dict:
    current = _prop_val(entity.get("modificationLog"))
    # Orion answers a one-element array as the bare object.
    if isinstance(current, list):
        log = list(current)
    elif isinstance(current, dict):
        log = [current]
    else:
        log = []
    log.append(entry)
    return {"type": "Property", "value": log}


@router.post("/operations/{operation_id}/correct")
async def api_correct_operation(operation_id: str, request: Request, body: dict):
    """Correct the dose of a completed irrigation operation created by the water-meter bridge."""
    tenant_id = _get_tenant(request)
    if _resolve_actor(_get_roles(request)) not in SENSOR_REVOKE_ACTORS:
        raise HTTPException(403, "Only a technical consultant or a tenant admin can correct sensor operations")
    entity = _get_or_404(tenant_id, operation_id)
    if (_prop_val(entity.get("status")) != "completed"
            or _prop_val(entity.get("dataSource")) != "sensor"
            or _prop_val(entity.get("operationType")) != "irrigation"):
        raise HTTPException(403, "Only completed sensor irrigation operations can be corrected")

    dose = body.get("waterPerHectare")
    if isinstance(dose, bool) or not isinstance(dose, (int, float)) or not dose > 0:
        raise HTTPException(422, "waterPerHectare must be a number greater than 0")
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise HTTPException(400, "reason is required")

    old_dose = _prop_val(entity.get("waterPerHectare"))
    old_vol = _prop_val(entity.get("waterVolume"))
    update = {"waterPerHectare": {"type": "Property", "value": dose}}
    entry = {
        "field": "waterPerHectare", "old": old_dose, "new": dose,
        "by": _get_user_id(request), "at": datetime.now(timezone.utc).isoformat(),
        "method": "manual_correction", "reason": reason.strip(),
    }
    numeric = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0  # noqa: E731
    if numeric(old_dose) and numeric(old_vol):
        # Keep the volume consistent with the corrected dose (same area).
        new_vol = round(old_vol * dose / old_dose, 3)
        update["waterVolume"] = {"type": "Property", "value": new_vol, "unitCode": "MTQ"}
        entry["fields"] = {"waterPerHectare": {"old": old_dose, "new": dose},
                           "waterVolume": {"old": old_vol, "new": new_vol}}
    update["modificationLog"] = _log_with(entity, entry)
    update_entity_attrs(tenant_id, operation_id, update)
    return {"operation_id": operation_id, "waterPerHectare": dose}


@router.post("/operations/{operation_id}/duplicate-review")
async def api_duplicate_review(operation_id: str, request: Request, body: dict):
    """Keep both a flagged water-meter irrigation and the manual one(s) it may duplicate.

    Writes only ``duplicateReview``: no modificationLog entry, so the bridge keeps updating the
    operation from late telemetry. 403: not a completed sensor irrigation; 400: not flagged;
    422: any decision but keep_both. Any authenticated user may decide."""
    tenant_id = _get_tenant(request)
    entity = _get_or_404(tenant_id, operation_id)
    if (_prop_val(entity.get("status")) != "completed"
            or _prop_val(entity.get("dataSource")) != "sensor"
            or _prop_val(entity.get("operationType")) != "irrigation"):
        raise HTTPException(403, "Only completed sensor irrigation operations can be reviewed")
    if not entity.get("possibleDuplicateOf"):
        raise HTTPException(400, "Operation is not flagged as a possible duplicate")
    if body.get("decision") != "keep_both":
        _unprocessable("invalid_decision", "decision must be keep_both")
    update_entity_attrs(tenant_id, operation_id, {"duplicateReview": {"type": "Property", "value": "keep_both"}})
    return {"operation_id": operation_id, "duplicateReview": "keep_both"}


@router.post("/operations/{operation_id}/cancel")
async def api_cancel_operation(operation_id: str, request: Request, body: dict):
    tenant_id = _get_tenant(request)
    entity = _get_or_404(tenant_id, operation_id)
    current_status = entity.get("status", {}).get("value", "")
    actor_role = _resolve_actor(_get_roles(request))
    data_source = _prop_val(entity.get("dataSource"))
    result = can_transition(current_status, "cancelled", actor_role, data_source=data_source)
    if not result.allowed:
        raise HTTPException(403, result.reason)

    reason = body.get("cancellationReason", "")
    if not reason:
        raise HTTPException(400, "cancellationReason is required")

    update = {
        "status": {"type": "Property", "value": "cancelled"},
        "cancellationReason": {"type": "Property", "value": reason},
    }
    if current_status == "completed":
        # A person's decision: the entry's author is what keeps the bridge away from it.
        update = _sensor_cancel_update(entity, _get_user_id(request), reason)
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

    file_data = label_photo.file.read()
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
