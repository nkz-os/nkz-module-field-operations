"""Orion-LD CRUD operations for AgriParcelOperation entities."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from .config import ORION_URL, CONTEXT_URL, VALID_OPERATION_TYPES

logger = logging.getLogger(__name__)


def _build_operation_id(tenant_id: str) -> str:
    return f"urn:ngsi-ld:AgriParcelOperation:{tenant_id}:{uuid.uuid4().hex[:12]}"


def _headers(tenant_id: str, content_type: str = "application/json") -> dict:
    return {
        "Accept": "application/ld+json",
        "Content-Type": content_type,
        "Link": f'<{CONTEXT_URL}>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"',
        "NGSILD-Tenant": tenant_id,
        "Fiware-Service": tenant_id,
        "Fiware-ServicePath": "/",
    }


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

    entity = {
        "id": entity_id,
        "type": "AgriParcelOperation",
        "hasAgriParcel": {"type": "Relationship", "object": parcel_id},
        "operationType": {"type": "Property", "value": operation_type},
        "workOrder": {"type": "Property", "value": work_order},
        "status": {"type": "Property", "value": "planned"},
        "operator": {"type": "Property", "value": operator},
        "dataSource": {"type": "Property", "value": data_source},
        "dateCreated": {"type": "Property", "value": {"@type": "DateTime", "@value": now}},
        "modificationLog": {"type": "Property", "value": []},
        "@context": [CONTEXT_URL],
    }

    if extra_attrs.get("tractor_id"):
        entity["usesTractor"] = {"type": "Relationship", "object": extra_attrs.pop("tractor_id")}
    if extra_attrs.get("implement_id"):
        entity["usesImplement"] = {"type": "Relationship", "object": extra_attrs.pop("implement_id")}

    for key, value in extra_attrs.items():
        if key in ("startedAt", "endedAt"):
            entity[key] = {"type": "Property", "value": {"@type": "DateTime", "@value": value}}
        elif isinstance(value, dict) and "unitCode" in value:
            entity[key] = {"type": "Property", "value": value["value"], "unitCode": value["unitCode"]}
        elif isinstance(value, dict):
            entity[key] = {"type": "Property", "value": value}
        else:
            entity[key] = {"type": "Property", "value": value}

    resp = httpx.post(
        f"{ORION_URL}/ngsi-ld/v1/entities",
        json=entity,
        headers=_headers(tenant_id, "application/ld+json"),
        timeout=10,
    )
    if resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"Orion-LD create failed ({resp.status_code}): {resp.text}")
    logger.info("Created AgriParcelOperation %s (status=planned)", entity_id)
    return entity


def get_entity(tenant_id: str, entity_id: str) -> Optional[dict]:
    resp = httpx.get(
        f"{ORION_URL}/ngsi-ld/v1/entities/{entity_id}",
        headers=_headers(tenant_id),
        timeout=10,
    )
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise RuntimeError(f"Orion-LD get failed ({resp.status_code}): {resp.text}")
    return resp.json()


def update_entity_attrs(tenant_id: str, entity_id: str, attrs: dict) -> dict:
    resp = httpx.patch(
        f"{ORION_URL}/ngsi-ld/v1/entities/{entity_id}/attrs",
        json=attrs,
        headers=_headers(tenant_id, "application/json"),
        timeout=10,
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

    params: dict = {"type": "AgriParcelOperation", "options": "keyValues", "limit": limit}
    if q_parts:
        params["q"] = ";".join(q_parts)

    resp = httpx.get(
        f"{ORION_URL}/ngsi-ld/v1/entities",
        params=params,
        headers=_headers(tenant_id),
        timeout=10,
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
            update[field] = {"type": "Property", "value": round(val * factor, 2), "unitCode": unit}

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


def _extract_unit(entity: dict, field: str) -> str:
    attr = entity.get(field)
    if isinstance(attr, dict):
        return attr.get("unitCode", "")
    return ""
