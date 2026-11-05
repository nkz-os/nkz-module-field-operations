"""Weekly farm report contribution: pending planned operations (contract v1).

Every pending operation (``planned`` or ``issued``) is a task, dated or not. The
aggregator applies the horizon; nothing is filtered by date here. Orion errors
are never swallowed: the caller answers 502, so an outage cannot read as
"nothing pending".
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from ..orion_ops import query_operations, query_parcel_names

logger = logging.getLogger(__name__)

PAGE = 1000
PENDING_STATUSES = ("planned", "issued")
PARCEL_PREFIX = "urn:ngsi-ld:AgriParcel:"

_KIND = {
    "sowing": "sow", "irrigation": "irrigate", "fertilization": "fertilize",
    "spraying": "treat", "tillage": "till", "harvesting": "harvest",
    "haymaking": "hay", "baling": "bale", "scouting": "scout",
}

# ASSUMPTION: eu wording is ours — confirm before shipping
_TITLES = {
    "sowing": {"es": "Siembra", "eu": "Ereintza", "en": "Sowing"},
    "irrigation": {"es": "Riego", "eu": "Ureztatzea", "en": "Irrigation"},
    "fertilization": {"es": "Abonado", "eu": "Ongarritzea", "en": "Fertilization"},
    "spraying": {"es": "Tratamiento fitosanitario", "eu": "Tratamendu fitosanitarioa", "en": "Spraying"},
    "tillage": {"es": "Labor del suelo", "eu": "Lurra lantzea", "en": "Tillage"},
    "harvesting": {"es": "Cosecha", "eu": "Uztaren bilketa", "en": "Harvest"},
    "haymaking": {"es": "Henificado", "eu": "Belar-ebaketa", "en": "Haymaking"},
    "baling": {"es": "Empacado", "eu": "Paketatzea", "en": "Baling"},
    "scouting": {"es": "Inspección del cultivo", "eu": "Laborantzaren ikuskapena", "en": "Crop scouting"},
}
_WHY = {
    "planned": {
        "es": "Labor planificada pendiente de realizar.",
        "eu": "Egiteko dagoen lan planifikatua.",
        "en": "Planned operation still to be carried out.",
    },
    "issued": {
        "es": "Orden recibida pendiente de revisión.",
        "eu": "Berrikusteko dagoen agindua.",
        "en": "Work order received, awaiting review.",
    },
}


def _plain(attr: Any) -> Any:
    """Unwrap a keyValues scalar, a DateTime dict or a normalized Property."""
    if isinstance(attr, dict):
        if "value" in attr and attr.get("type") == "Property":
            return _plain(attr["value"])
        if "@value" in attr:
            return attr["@value"]
        if "object" in attr:
            return attr["object"]
    return attr


def _planned_day(op: dict) -> Optional[str]:
    raw = _plain(op.get("plannedDate"))
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        return None


def _all_pending(tenant_id: str) -> list[dict]:
    rows: list[dict] = []
    for status in PENDING_STATUSES:
        offset = 0
        while True:
            page = query_operations(tenant_id, status=status, limit=PAGE, offset=offset)
            rows.extend(page)
            if len(page) < PAGE:
                break
            offset += PAGE
    return rows


def _parcel_name(parcel_id: str, names: dict) -> str:
    name = names.get(parcel_id)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return parcel_id.rsplit(":", 1)[-1][:8]


def build(tenant_id: str, week_start: date) -> dict:
    """Raises on any Orion failure (RuntimeError / requests errors)."""
    names = query_parcel_names(tenant_id)
    tasks = []
    for op in _all_pending(tenant_id):
        status = _plain(op.get("status"))
        op_type = _plain(op.get("operationType"))
        parcel_id = _plain(op.get("hasAgriParcel") or op.get("refAgriParcel"))
        if status not in PENDING_STATUSES or op_type not in _TITLES:
            continue
        if not isinstance(parcel_id, str) or not parcel_id:
            logger.warning("weekly-report: operation without parcel skipped tenant=%s op=%s", tenant_id, op.get("id"))
            continue
        day = _planned_day(op)
        tasks.append({
            "id": op["id"],
            "subject": {"type": "parcel", "id": parcel_id, "name": _parcel_name(parcel_id, names)},
            "kind": _KIND[op_type],
            "when": {"type": "date", "date": day} if day else {"type": "undated", "date": None},
            "text": {lang: {"title": _TITLES[op_type][lang], "why": _WHY[status][lang]} for lang in ("es", "eu", "en")},
            "link": {"kind": "open_parcel", "params": {"parcel_id": parcel_id}},
            "relatedAlertId": None,
        })
    return {"version": 1, "complete": True, "tasks": tasks, "changes": [], "figures": []}
