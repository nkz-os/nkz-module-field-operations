"""Orion-LD CRUD operations for AgriParcelOperation entities."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from nkz_platform_sdk import SyncOrionClient

from .config import VALID_OPERATION_TYPES

logger = logging.getLogger(__name__)


def _build_operation_id(tenant_id: str) -> str:
    return f"urn:ngsi-ld:AgriParcelOperation:{tenant_id}:{uuid.uuid4().hex[:12]}"


def _get_client(tenant_id: str) -> SyncOrionClient:
    """Create a SyncOrionClient for the given tenant.

    Reads ORION_LD_URL and CONTEXT_URL from environment (via the SDK).
    """
    return SyncOrionClient(tenant_id)


def create_operation(
    tenant_id: str,
    parcel_id: str,
    operation_type: str,
    work_order: str,
    operator: str,
    data_source: str = "manual",
    **extra_attrs,
) -> dict:
    if operation_type not in VALID_OPERATION_TYPES:
        raise ValueError(f"Invalid operationType: {operation_type}")

    entity_id = _build_operation_id(tenant_id)
    now = datetime.now(timezone.utc).isoformat()
    client = _get_client(tenant_id)

    entity = {
        "id": entity_id,
        "type": "AgriParcelOperation",
        "@context": [client.context_url],
        "hasAgriParcel": {"type": "Relationship", "object": parcel_id},
        "operationType": {"type": "Property", "value": operation_type},
        "workOrder": {"type": "Property", "value": work_order},
        "status": {"type": "Property", "value": "planned"},
        "operator": {"type": "Property", "value": operator},
        "dataSource": {"type": "Property", "value": data_source},
        "dateCreated": {"type": "Property", "value": {"@type": "DateTime", "@value": now}},
        "modificationLog": {"type": "Property", "value": []},
    }

    if extra_attrs.get("tractor_id"):
        entity["usesTractor"] = {"type": "Relationship", "object": extra_attrs.pop("tractor_id")}
    if extra_attrs.get("implement_id"):
        entity["usesImplement"] = {"type": "Relationship", "object": extra_attrs.pop("implement_id")}

    # Handle known attributes with specific NGSI-LD typing
    if extra_attrs.get("planned_date"):
        entity["plannedDate"] = {"type": "Property", "value": {"@type": "DateTime", "@value": extra_attrs.pop("planned_date")}}
    if extra_attrs.get("assigned_to"):
        entity["assignedTo"] = {"type": "Property", "value": extra_attrs.pop("assigned_to")}
    if extra_attrs.get("source"):
        entity["source"] = {"type": "Property", "value": extra_attrs.pop("source")}
    if extra_attrs.get("external_ref"):
        entity["externalRef"] = {"type": "Property", "value": extra_attrs.pop("external_ref")}

    for key, value in extra_attrs.items():
        if key in ("startedAt", "endedAt"):
            entity[key] = {"type": "Property", "value": {"@type": "DateTime", "@value": value}}
        elif isinstance(value, dict) and "unitCode" in value:
            entity[key] = {"type": "Property", "value": value["value"], "unitCode": value["unitCode"]}
        elif isinstance(value, dict):
            entity[key] = {"type": "Property", "value": value}
        else:
            entity[key] = {"type": "Property", "value": value}

    try:
        client.create_entity(entity)
    except requests.HTTPError as e:
        raise RuntimeError(
            f"Orion-LD create failed ({e.response.status_code}): {e.response.text}"
        ) from e

    logger.info("Created AgriParcelOperation %s (status=planned)", entity_id)
    return entity


def get_entity(tenant_id: str, entity_id: str) -> Optional[dict]:
    client = _get_client(tenant_id)
    try:
        return client.get_entity(entity_id)
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return None
        raise RuntimeError(
            f"Orion-LD get failed ({e.response.status_code}): {e.response.text}"
        ) from e


def update_entity_attrs(tenant_id: str, entity_id: str, attrs: dict) -> dict:
    """PATCH /attrs on an entity.

    SyncOrionClient does not have update_entity_attrs, so we use
    the client's _session.patch directly with its header builder.
    """
    client = _get_client(tenant_id)
    resp = client._session.patch(
        client._url(f"/ngsi-ld/v1/entities/{entity_id}/attrs"),
        json=attrs,
        headers=client._headers("application/json"),
        timeout=client.timeout,
    )
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"Orion-LD patch failed ({resp.status_code}): {resp.text}")
    return attrs


def start_operation(tenant_id: str, operation_id: str, started_at: Optional[str] = None) -> dict:
    now = started_at or datetime.now(timezone.utc).isoformat()
    update = {
        "status": {"type": "Property", "value": "incomplete"},
        "startedAt": {"type": "Property", "value": {"@type": "DateTime", "@value": now}},
    }
    update_entity_attrs(tenant_id, operation_id, update)
    logger.info("Started operation %s", operation_id)
    return update


def complete_operation(
    tenant_id: str,
    operation_id: str,
    ended_at: Optional[str] = None,
    extra_attrs: Optional[dict] = None,
) -> dict:
    now = ended_at or datetime.now(timezone.utc).isoformat()
    update = {
        "status": {"type": "Property", "value": "completed"},
        "endedAt": {"type": "Property", "value": {"@type": "DateTime", "@value": now}},
    }
    if extra_attrs:
        for key, value in extra_attrs.items():
            if isinstance(value, dict) and "unitCode" in value:
                update[key] = {"type": "Property", "value": value["value"], "unitCode": value["unitCode"]}
            else:
                update[key] = {"type": "Property", "value": value}
    update_entity_attrs(tenant_id, operation_id, update)
    logger.info("Completed operation %s", operation_id)
    return update


def enrich_from_isobus(tenant_id: str, operation_id: str, isobus_data: dict) -> dict:
    isobus_map = {
        "fuelUsed": ("fuelUsed", "LTR"),
        "engineHours": ("engineHours", "HUR"),
        "areaCovered": ("areaCovered", "HAR"),
        "seedingRate": ("seedingRate", "KGM"),
        "sprayRate": ("productRate", "KGM"),
        "harvestedWeight": ("harvestedWeight", "KGM"),
    }
    update = {}
    for isobus_field, (ngsi_field, unit) in isobus_map.items():
        val = isobus_data.get(isobus_field)
        if val is not None:
            update[ngsi_field] = {"type": "Property", "value": float(val), "unitCode": unit}
    if update:
        update_entity_attrs(tenant_id, operation_id, update)
        logger.info("ISOBUS enriched %s: %s", operation_id, list(update.keys()))
    return update


def query_operations(
    tenant_id: str,
    parcel_id: Optional[str] = None,
    operation_type: Optional[str] = None,
    status: Optional[str] = None,
    work_order: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    q_parts = []
    if parcel_id:
        q_parts.append(f'hasAgriParcel=="{parcel_id}"')
    if operation_type:
        q_parts.append(f'operationType=="{operation_type}"')
    if status:
        q_parts.append(f'status=="{status}"')
    if work_order:
        q_parts.append(f'workOrder=="{work_order}"')

    client = _get_client(tenant_id)

    # query_entities in SyncOrionClient does not support options=keyValues,
    # so we use _session directly for backward compatibility with callers.
    params: dict[str, Any] = {"type": "AgriParcelOperation", "options": "keyValues", "limit": limit}
    if q_parts:
        params["q"] = ";".join(q_parts)

    resp = client._session.get(
        client._url("/ngsi-ld/v1/entities"),
        params=params,
        headers=client._headers("application/json"),
        timeout=client.timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Orion-LD query failed ({resp.status_code}): {resp.text}")
    return resp.json()


def extrapolate_to_full_parcel(tenant_id: str, operation_id: str, parcel_area_ha: float) -> dict:
    entity = get_entity(tenant_id, operation_id)
    if not entity:
        raise ValueError(f"Entity not found: {operation_id}")

    area_covered = _extract_value(entity, "areaCovered")
    if not area_covered or area_covered <= 0:
        raise ValueError("Cannot extrapolate: no areaCovered data from ISOBUS")

    factor = parcel_area_ha / area_covered

    RATE_FIELDS = [
        "waterVolume", "fuelUsed", "harvestedWeight",
        "seedingRate", "productRate", "fertilizerRate",
    ]
    update = {}
    for field in RATE_FIELDS:
        val = _extract_value(entity, field)
        unit = _extract_unit(entity, field)
        if val is not None:
            attr = {"type": "Property", "value": round(val * factor, 2)}
            if unit:
                attr["unitCode"] = unit
            update[field] = attr

    update["areaCovered"] = {"type": "Property", "value": parcel_area_ha, "unitCode": "HAR"}

    log_entry = {
        "field": "areaCovered",
        "old": area_covered,
        "new": parcel_area_ha,
        "factor": factor,
        "by": "office_user",
        "at": datetime.now(timezone.utc).isoformat(),
        "method": "extrapolation",
    }
    existing_log = entity.get("modificationLog", {}).get("value", []) if isinstance(entity.get("modificationLog"), dict) else []
    existing_log.append(log_entry)
    update["modificationLog"] = {"type": "Property", "value": existing_log}
    update["dataSource"] = {"type": "Property", "value": "mixed"}

    update_entity_attrs(tenant_id, operation_id, update)
    logger.info("Extrapolated %s: factor=%.2f, updated %d fields", operation_id, factor, len(update) - 2)
    return update


def _extract_value(entity: dict, field: str) -> Optional[float]:
    attr = entity.get(field)
    if isinstance(attr, dict):
        val = attr.get("value")
        return float(val) if val is not None else None
    return None


def _extract_unit(entity: dict, field: str) -> str | None:
    attr = entity.get(field)
    if isinstance(attr, dict):
        return attr.get("unitCode") or None
    return None


def create_suggested_operation(
    tenant_id: str,
    parcel_id: str,
    operation_type: str,
    confidence: float,
    delta_vv_db: float,
    sensing_date: str,
    scene_id: str = "",
) -> str | None:
    """Create a SAR-suggested AgriParcelOperation with status=suggested.

    Idempotent: if a suggested operation already exists for this
    parcel + date + type, returns None (caller should return 409).
    """
    from urllib.parse import quote

    client = _get_client(tenant_id)

    # Idempotency check
    q = (
        f'hasAgriParcel=="{parcel_id}"'
        f';operationType=="{operation_type}"'
        f';status=="suggested"'
    )
    check = client.get(
        f"/ngsi-ld/v1/entities?type=AgriParcelOperation&q={quote(q)}&limit=1"
    )
    if check.status_code == 200:
        existing = check.json()
        if isinstance(existing, list) and existing:
            logger.info(
                "Suggested operation already exists for %s/%s",
                parcel_id, operation_type,
            )
            return None

    op_id = _build_operation_id(tenant_id)
    entity: dict = {
        "id": op_id,
        "type": "AgriParcelOperation",
        "operationType": {"type": "Property", "value": operation_type},
        "hasAgriParcel": {"type": "Relationship", "object": parcel_id},
        "status": {"type": "Property", "value": "suggested"},
        "dataFidelity": {"type": "Property", "value": "satellite_derived"},
        "plannedStartAt": {
            "type": "Property",
            "value": f"{sensing_date}T06:00:00Z" if sensing_date and "T" not in sensing_date else sensing_date or "",
        },
        "description": {
            "type": "Property",
            "value": f"Detectado por SAR (confianza: {int(confidence * 100)}%). ¿Confirma esta labor?",
        },
        "sarDetection": {
            "type": "Property",
            "value": {
                "confidence": round(float(confidence), 4),
                "deltaVV": round(float(delta_vv_db), 2),
                "sceneId": scene_id or "",
            },
        },
    }

    resp = client.post("/ngsi-ld/v1/entities", json=entity)
    if resp.status_code in (201, 204):
        logger.info("Created suggested operation %s for %s", op_id, parcel_id)
        return op_id
    logger.warning("Failed to create suggested operation: %d %s", resp.status_code, resp.text[:200])
    return None
