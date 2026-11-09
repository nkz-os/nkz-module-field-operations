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
    """Every pending row, de-duplicated by id (a row can repeat across pages)."""
    rows: list[dict] = []
    seen: set[str] = set()
    for status in PENDING_STATUSES:
        offset = 0
        while True:
            page = query_operations(tenant_id, status=status, limit=PAGE, offset=offset)
            for row in page:
                op_id = row.get("id")
                if op_id:
                    if op_id in seen:
                        continue
                    seen.add(op_id)
                rows.append(row)
            if len(page) < PAGE:
                break
            offset += PAGE
    return rows


def _parcel_name(parcel_id: str, names: dict) -> str:
    name = names.get(parcel_id)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return parcel_id.rsplit(":", 1)[-1][:8]


# ASSUMPTION: eu wording is ours — confirm before shipping
_UNKNOWN_TITLE = {
    "es": "Operación pendiente",
    "eu": "Zain dagoen eragiketa",
    "en": "Pending operation",
}
_NO_PARCEL_TITLE = {
    "es": "Operación pendiente sin parcela asignada",
    "eu": "Lursailik esleitu gabeko eragiketa zain",
    "en": "Pending operation with no parcel assigned",
}


def build(tenant_id: str, week_start: date) -> dict:
    """Raises on any Orion failure (RuntimeError / requests errors)."""
    names = query_parcel_names(tenant_id)
    tasks = []
    complete = True
    for op in _all_pending(tenant_id):
        if not op.get("id"):
            logger.error("weekly-report: pending row without id cannot be shown tenant=%s", tenant_id)
            complete = False
            continue
        status = _plain(op.get("status"))
        if status not in PENDING_STATUSES:
            continue
        op_type = _plain(op.get("operationType"))
        parcel_id = _plain(op.get("hasAgriParcel") or op.get("refAgriParcel"))
        has_parcel = isinstance(parcel_id, str) and bool(parcel_id)
        known = op_type in _TITLES
        if has_parcel:
            subject = {"type": "parcel", "id": parcel_id, "name": _parcel_name(parcel_id, names)}
            link = {"kind": "open_parcel", "params": {"parcel_id": parcel_id}}
        else:
            logger.warning("weekly-report: operation without parcel tenant=%s op=%s", tenant_id, op["id"])
            subject = {"type": "farm", "id": "", "name": ""}
            link = None
        if not has_parcel:
            titles = _NO_PARCEL_TITLE
        elif known:
            titles = _TITLES[op_type]
        else:
            logger.warning("weekly-report: unknown operation type tenant=%s op=%s", tenant_id, op["id"])
            titles = _UNKNOWN_TITLE
        tasks.append({
            "id": op["id"],
            "subject": subject,
            "kind": _KIND.get(op_type, "other"),
            "when": _when(op),
            "text": {lang: {"title": titles[lang], "why": _WHY[status][lang]} for lang in ("es", "eu", "en")},
            "link": link,
            "relatedAlertId": None,
        })
    return {"version": 1, "complete": complete, "tasks": tasks, "changes": [], "figures": []}


def _when(op: dict) -> dict:
    day = _planned_day(op)
    return {"type": "date", "date": day} if day else {"type": "undated", "date": None}
