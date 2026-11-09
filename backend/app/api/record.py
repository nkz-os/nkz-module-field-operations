"""Record a sowing or a harvest that already happened, and list what can be recorded.

Mounted behind the gateway identity: the tenant header is trusted only once its
signature checks out, and the operator is the verified user.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from datetime import date, timedelta

import httpx
import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from nkz_platform_sdk.crop_cycles import UPROOTING, resolve_crop_cycles
from nkz_platform_sdk.crop_timeline import (
    CropDataUnavailable,
    ParcelNotFound,
    load_crop_data,
    local_today,
    normalize_parcel_urn,
)
from nkz_platform_sdk.orion import OrionClient

from .. import config
from ..config import REQUIRED_FIELDS
from ..orion_ops import EntityAlreadyExists, create_operation
from ..services.crop_cycles_writer import reconcile_parcel
from ..services.record import RECORDABLE, current_cycle, match_record
from ..services.record_types import NEW_TYPES, RecordError, build_attrs
from ..state_machine import validate_sowing_method

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/field-operations", tags=["record"])

_FACTS = ("actual", "declared")
_CLOSED = ("harvested", "terminated")
_CONCURRENCY = 5
_PARCEL = re.compile(r"^(urn:ngsi-ld:AgriParcel:)?[A-Za-z0-9._:-]{1,200}$")
_NUMBERS = ("seedingRate", "harvestedWeight")
_NOTES_MAX = 500
_UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _orion(tenant_id: str) -> OrionClient:
    return OrionClient(tenant_id, base_url=config.ORION_URL, context_url=config.CONTEXT_URL)


def _today(parcel: dict) -> date:
    return local_today(parcel)


def _unprocessable(code: str, detail: str):
    raise HTTPException(status_code=422, detail={"code": code, "detail": detail})


def _positive(field: str, raw) -> float:
    try:
        value = float(str(raw).replace(",", "."))
    except ValueError:
        value = float("nan")
    if not math.isfinite(value) or value <= 0:
        _unprocessable("invalid_number", f"{field} must be a positive number")
    return value


def _parse_day(raw) -> date:
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        _unprocessable("invalid_date", "date must be YYYY-MM-DD")


def _value(attr):
    return attr.get("value") if isinstance(attr, dict) else attr


def _first(entity: dict, *names):
    for name in names:
        if name in entity:
            return entity[name]
    return None


def _stored_view(entity: dict) -> dict:
    """The 200 answer for a record that already exists, from what the entity keeps."""
    op_type = _value(entity.get("operationType"))
    if op_type == "tillage" and _value(entity.get("tillageType")) == UPROOTING:
        op_type = "uprooting"
    parcel = _first(entity, "hasAgriParcel")
    crop = _first(entity, "hasAgriCrop")
    started = _value(entity.get("startedAt"))
    if isinstance(started, dict):
        started = started.get("@value")
    return {"operation_id": entity.get("id"), "operation_type": op_type,
            "parcel_id": parcel.get("object") if isinstance(parcel, dict) else parcel,
            "date": str(started)[:10] if started else None, "duplicate": True,
            "crop_id": (crop.get("object") if isinstance(crop, dict) else crop) if crop else None,
            "species": None, "role": None, "campaign": None, "harvest_campaign": None,
            "harvest_campaign_label": None, "reconciled": False}


async def existing_record(client, entity_id: str) -> dict | None:
    """The stored entity for a client id, or None when it was never written."""
    try:
        return await client.get_entity(entity_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise


async def _lookup(client, tenant_id: str, entity_id: str) -> dict | None:
    try:
        return await existing_record(client, entity_id)
    except (httpx.HTTPError, RuntimeError) as exc:
        logger.error("record: client_id lookup failed tenant=%s entity=%s: %s", tenant_id, entity_id, exc)
        raise HTTPException(status_code=503, detail={"code": "store_unavailable", "detail": str(exc)})


def _duplicate(entity: dict, body: dict, day: date, op_type: str, tenant_id: str):
    view = _stored_view(entity)
    if view["operation_type"] != op_type or view["date"] != day.isoformat() \
            or (body.get("parcel_id") and view["parcel_id"] != normalize_parcel_urn(str(body["parcel_id"]))):
        logger.warning("record: client_id reused with a body that differs from the stored record "
                       "tenant=%s entity=%s", tenant_id, entity.get("id"))
    return JSONResponse(status_code=200, content=view)


def _common(body: dict, tenant_id: str) -> str | None:
    """Notes and client id, shared by every type; returns the deterministic entity id."""
    notes = body.get("notes")
    if notes is not None and (not isinstance(notes, str) or len(notes) > _NOTES_MAX):
        _unprocessable("invalid_notes", f"notes must be text of at most {_NOTES_MAX} characters")
    client_id = body.get("client_id")
    if client_id is not None:
        client_id = client_id.lower() if isinstance(client_id, str) else client_id
        if not isinstance(client_id, str) or not _UUID4.match(client_id):
            _unprocessable("invalid_client_id", "client_id must be a UUIDv4")
    return f"urn:ngsi-ld:AgriParcelOperation:{tenant_id}:{client_id}" if client_id else None


async def _crop_data(client, parcel_urn: str):
    try:
        return await load_crop_data(client, parcel_urn)
    except ParcelNotFound:
        raise HTTPException(status_code=404, detail={"code": "parcel_not_found", "detail": parcel_urn})
    except CropDataUnavailable as exc:
        logger.warning("record: crop data unavailable parcel=%s: %s", parcel_urn, exc)
        raise HTTPException(status_code=503, detail={"code": "crop_data_unavailable", "detail": str(exc)})


async def _fact_parcel(client, parcel_urn: str) -> dict:
    try:
        return await client.get_entity(parcel_urn, options="keyValues")
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail={"code": "parcel_not_found", "detail": parcel_urn})
        logger.error("record: parcel read failed parcel=%s: %s", parcel_urn, exc)
        raise HTTPException(status_code=503, detail={"code": "store_unavailable", "detail": str(exc)})
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        logger.error("record: parcel read failed parcel=%s: %s", parcel_urn, exc)
        raise HTTPException(status_code=503, detail={"code": "store_unavailable", "detail": str(exc)})


async def _fact_crop(client, parcel_urn: str, day: date, today: date, required: bool):
    """The single standing crop (best effort); only haymaking and baling cannot do without it."""
    try:
        _, crops, ops = await load_crop_data(client, parcel_urn)
        return current_cycle(parcel_urn, crops, ops, day, today)
    except Exception as exc:  # noqa: BLE001 — a watering never waits for the crop read
        if required:
            logger.warning("record: crop data unavailable parcel=%s: %s", parcel_urn, exc)
            raise HTTPException(status_code=503, detail={"code": "crop_data_unavailable", "detail": str(exc)})
        logger.warning("record: crop lookup failed, recording without hasAgriCrop parcel=%s: %s", parcel_urn, exc)
        return None


async def _record_fact(tenant_id: str, user_id: str, op_type: str, day: date, body: dict):
    """A completed fact of one of the types that take no crop window (spec 3a, 3.2)."""
    if not body.get("parcel_id"):
        _unprocessable("missing_fields", "parcel_id is required")
    if not _PARCEL.match(str(body["parcel_id"])):
        _unprocessable("invalid_parcel", "parcel_id is not a parcel id")
    try:
        attrs = build_attrs(op_type, body)
    except RecordError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": exc.detail})
    entity_id = _common(body, tenant_id)
    parcel_urn = normalize_parcel_urn(str(body["parcel_id"]))
    client = _orion(tenant_id)
    try:
        if entity_id:
            stored = await _lookup(client, tenant_id, entity_id)
            if stored:
                return _duplicate(stored, body, day, op_type, tenant_id)
        parcel = await _fact_parcel(client, parcel_urn)
        today = _today(parcel)
        if day > today + timedelta(days=1):
            raise HTTPException(status_code=409, detail={"code": "future_date"})
        needs_crop = op_type in ("haymaking", "baling")
        cycle = await _fact_crop(client, parcel_urn, day, today, needs_crop)
        if needs_crop:
            if cycle is None or not cycle.species:
                raise HTTPException(status_code=409, detail={"code": "no_crop_on_date"})
            attrs["cropType"] = cycle.species
        if cycle:
            attrs["crop_id"] = cycle.crop_id

        stamp = f"{day.isoformat()}T12:00:00Z"
        extra = {"entity_id": entity_id} if entity_id else {}
        try:
            entity = await asyncio.to_thread(
                create_operation, tenant_id,
                parcel_id=parcel_urn, operation_type=op_type, work_order=f"REG-{day.isoformat()}",
                operator=user_id, data_source="manual", status="completed",
                startedAt=stamp, endedAt=stamp, **extra, **attrs,
            )
        except EntityAlreadyExists:
            stored = await _lookup(client, tenant_id, entity_id) if entity_id else None
            if not stored:
                raise HTTPException(status_code=503, detail={"code": "store_unavailable",
                                                             "detail": "entity exists but cannot be read"})
            return _duplicate(stored, body, day, op_type, tenant_id)
        except (RuntimeError, requests.RequestException) as exc:
            logger.error("record: write failed tenant=%s parcel=%s: %s", tenant_id, parcel_urn, exc)
            raise HTTPException(status_code=503, detail={"code": "store_unavailable", "detail": str(exc)})
        logger.info("record: %s tenant=%s parcel=%s crop=%s op=%s", op_type, tenant_id, parcel_urn,
                    cycle.crop_id if cycle else None, entity.get("id"))

        reconciled = False
        if op_type == "tillage" and config.CROP_CYCLES_WRITER_ENABLED:
            # Rolling or mowing a cover ends it in the SDK: show it at once.
            try:
                await reconcile_parcel(client, tenant_id, parcel_urn)
                reconciled = True
            except Exception as exc:  # noqa: BLE001 — the record stands; the sweep catches up
                logger.warning("record: reconcile failed tenant=%s parcel=%s: %s", tenant_id, parcel_urn, exc)
        answer = {"operation_id": entity.get("id"), "operation_type": op_type, "parcel_id": parcel_urn,
                  "date": day.isoformat(), "duplicate": False, "crop_id": cycle.crop_id if cycle else None,
                  "species": None, "role": None, "campaign": None, "harvest_campaign": None,
                  "harvest_campaign_label": None, "reconciled": reconciled}
        if op_type == "spraying":
            answer["authorization"] = "not_checked"  # no CUE check in v1
        return JSONResponse(status_code=201, content=answer)
    finally:
        await client.close()


@router.post("/operations/record", status_code=201)
async def record_operation(request: Request, body: dict):
    tenant_id = request.state.tenant_id
    user_id = request.state.user_id
    op_type = body.get("operation_type")
    if op_type not in RECORDABLE:
        _unprocessable("unsupported_type", f"operation_type must be one of: {', '.join(RECORDABLE)}")
    if not body.get("parcel_id"):
        _unprocessable("missing_fields", "parcel_id is required")
    if not _PARCEL.match(str(body["parcel_id"])):
        _unprocessable("invalid_parcel", "parcel_id is not a parcel id")
    day = _parse_day(body.get("date"))
    if op_type in NEW_TYPES:
        return await _record_fact(tenant_id, user_id, op_type, day, body)
    error = validate_sowing_method(op_type, body)
    if error:
        _unprocessable("invalid_sowing_method", error)

    # Fields only the user can give are checked before reading anything; the crop
    # (and a planned variety) come from the plan the record lands on.
    _FROM_PLAN = ("cropType", "variety")
    missing = [f for f in REQUIRED_FIELDS.get(op_type, []) if f not in _FROM_PLAN and body.get(f) in (None, "")]
    if missing:
        _unprocessable("missing_fields", f"missing: {', '.join(missing)}")
    for field in _NUMBERS:
        if body.get(field) not in (None, ""):
            _positive(field, body[field])

    entity_id = _common(body, tenant_id)

    parcel_urn = normalize_parcel_urn(str(body["parcel_id"]))
    client = _orion(tenant_id)
    try:
        if entity_id:
            stored = await _lookup(client, tenant_id, entity_id)
            if stored:
                return _duplicate(stored, body, day, op_type, tenant_id)
        parcel, crops, ops = await _crop_data(client, parcel_urn)
        match = match_record(parcel_urn, crops, ops, op_type, day, _today(parcel))
        if not match.ok:
            raise HTTPException(status_code=409, detail={"code": match.reason})
        chosen = body.get("crop_id")
        if chosen and chosen != match.crop_id:
            # The form names the crop the user meant; the date decides where the platform puts it.
            raise HTTPException(status_code=409, detail={"code": "date_outside_crop_window",
                                                         "landed_on": match.crop_id})

        attrs = {k: body[k] for k in ("seedingRate", "sowingMethod", "harvestedWeight",
                                       "harvestDestination", "notes") if body.get(k) not in (None, "")}
        for field in _NUMBERS:
            if field in attrs:
                attrs[field] = _positive(field, attrs[field])
        stored_type = op_type
        if op_type == "uprooting":
            stored_type, attrs["tillageType"] = "tillage", UPROOTING
            # The same stand the matcher probed: the shared rule must resolve the stored op identically.
            attrs["crop_id"] = match.crop_id
        if op_type == "sowing":
            attrs["cropType"] = match.species
            attrs["variety"] = body.get("variety") or match.variety
        missing = [f for f in REQUIRED_FIELDS[stored_type] if attrs.get(f) in (None, "")]
        if missing:
            _unprocessable("missing_fields", f"missing: {', '.join(missing)}")

        stamp = f"{day.isoformat()}T12:00:00Z"  # the day is the fact; noon keeps it in every time zone
        extra = {"entity_id": entity_id} if entity_id else {}
        try:
            entity = await asyncio.to_thread(
                create_operation, tenant_id,
                parcel_id=parcel_urn, operation_type=stored_type, work_order=f"REG-{day.isoformat()}",
                operator=user_id, data_source="manual", status="completed",
                startedAt=stamp, endedAt=stamp, **extra, **attrs,
            )
        except EntityAlreadyExists:
            # A concurrent retry wrote it first: answer with what is stored.
            stored = await _lookup(client, tenant_id, entity_id) if entity_id else None
            if not stored:
                raise HTTPException(status_code=503, detail={"code": "store_unavailable",
                                                             "detail": "entity exists but cannot be read"})
            return _duplicate(stored, body, day, op_type, tenant_id)
        except (RuntimeError, requests.RequestException) as exc:
            # Nothing was stored; a retry after a lost answer is refused as already_recorded.
            logger.error("record: write failed tenant=%s parcel=%s: %s", tenant_id, parcel_urn, exc)
            raise HTTPException(status_code=503, detail={"code": "store_unavailable", "detail": str(exc)})
        logger.info("record: %s tenant=%s parcel=%s crop=%s op=%s", op_type, tenant_id, parcel_urn,
                    match.crop_id, entity.get("id"))

        reconciled = False
        if config.CROP_CYCLES_WRITER_ENABLED:
            # Shows the crop as sown at once; the notification and the daily sweep do it again.
            try:
                await reconcile_parcel(client, tenant_id, parcel_urn)
                reconciled = True
            except Exception as exc:  # noqa: BLE001 — the record stands; the sweep catches up
                logger.warning("record: reconcile failed tenant=%s parcel=%s: %s", tenant_id, parcel_urn, exc)
        return {"operation_id": entity.get("id"), "operation_type": op_type, "parcel_id": parcel_urn,
                "date": day.isoformat(), "duplicate": False, "crop_id": match.crop_id, "species": match.species,
                "role": match.role, "campaign": match.campaign, "harvest_campaign": match.harvest_campaign,
                "harvest_campaign_label": match.harvest_campaign_label,
                "reconciled": reconciled}
    finally:
        await client.close()


def _cycle_view(cy, crops_by_id: dict) -> dict:
    d = cy.to_dict()
    crop = crops_by_id.get(cy.crop_id, {})
    variety = crop.get("variety")
    d["variety"] = variety.get("value") if isinstance(variety, dict) else variety
    name = crop.get("name")
    d["name"] = name if isinstance(name, str) else None
    open_ = cy.status not in _CLOSED
    d["can_sow"] = open_ and cy.start.provenance not in _FACTS
    d["can_harvest"] = open_ and cy.start.provenance in _FACTS and cy.end.provenance != "actual"
    d["can_uproot"] = d["can_harvest"] and cy.lifecycle == "perennial"
    d["harvest_campaigns"] = [c.to_dict() for c in cy.harvest_campaigns]
    return d


async def _parcel_view(tenant_id: str, parcel: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        client = _orion(tenant_id)
        try:
            full, crops, ops = await load_crop_data(client, parcel["id"])
            timeline = resolve_crop_cycles(parcel["id"], crops, ops, local_today(full))
            by_id = {c.get("id"): c for c in crops}
            cycles = [_cycle_view(cy, by_id) for cy in timeline.cycles]
            cycles = [c for c in cycles if c["can_sow"] or c["can_harvest"] or c["can_uproot"]]
            readable = True
        except Exception as exc:  # noqa: BLE001 — one unreadable parcel never hides the others
            logger.warning("record: parcel unreadable tenant=%s parcel=%s: %s", tenant_id, parcel.get("id"), exc)
            cycles, readable = [], False
        finally:
            await client.close()
    name = parcel.get("name")
    return {"id": parcel["id"], "name": name if isinstance(name, str) else None, "area": parcel.get("area"),
            "cycles": cycles, "readable": readable}


@router.get("/parcels")
async def list_recordable_parcels(request: Request):
    """Every parcel of the tenant with the crops that can be sown or harvested now."""
    tenant_id = request.state.tenant_id
    client = _orion(tenant_id)
    try:
        parcels, offset = [], 0
        while True:
            page = await client.query_entities(type="AgriParcel", limit=500, offset=offset, options="keyValues")
            parcels.extend(p for p in page or [] if p.get("id"))
            if not page or len(page) < 500:
                break
            offset += 500
    except Exception as exc:  # noqa: BLE001 — the form shows a retry, never a 500
        logger.warning("record: parcel list unavailable tenant=%s: %s", tenant_id, exc)
        raise HTTPException(status_code=503, detail={"code": "crop_data_unavailable", "detail": str(exc)})
    finally:
        await client.close()
    sem = asyncio.Semaphore(_CONCURRENCY)
    views = await asyncio.gather(*(_parcel_view(tenant_id, p, sem) for p in parcels))
    return {"parcels": sorted(views, key=lambda v: (v["name"] or v["id"]).lower())}
