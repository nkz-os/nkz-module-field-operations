"""Record a sowing or a harvest that already happened, and list what can be recorded.

Mounted behind the gateway identity: the tenant header is trusted only once its
signature checks out, and the operator is the verified user.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from nkz_platform_sdk.crop_cycles import resolve_crop_cycles
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
from ..orion_ops import create_operation
from ..services.crop_cycles_writer import reconcile_parcel
from ..services.record import RECORDABLE, match_record
from ..state_machine import validate_sowing_method

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/field-operations", tags=["record"])

_FACTS = ("actual", "declared")
_CLOSED = ("harvested", "terminated")
_CONCURRENCY = 5


def _orion(tenant_id: str) -> OrionClient:
    return OrionClient(tenant_id, base_url=config.ORION_URL, context_url=config.CONTEXT_URL)


def _today(parcel: dict) -> date:
    return local_today(parcel)


def _unprocessable(code: str, detail: str):
    raise HTTPException(status_code=422, detail={"code": code, "detail": detail})


def _parse_day(raw) -> date:
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        _unprocessable("invalid_date", "date must be YYYY-MM-DD")


async def _crop_data(client, parcel_urn: str):
    try:
        return await load_crop_data(client, parcel_urn)
    except ParcelNotFound:
        raise HTTPException(status_code=404, detail={"code": "parcel_not_found", "detail": parcel_urn})
    except CropDataUnavailable as exc:
        logger.warning("record: crop data unavailable parcel=%s: %s", parcel_urn, exc)
        raise HTTPException(status_code=503, detail={"code": "crop_data_unavailable", "detail": str(exc)})


@router.post("/operations/record", status_code=201)
async def record_operation(request: Request, body: dict):
    tenant_id = request.state.tenant_id
    user_id = request.state.user_id
    op_type = body.get("operation_type")
    if op_type not in RECORDABLE:
        _unprocessable("unsupported_type", f"operation_type must be one of: {', '.join(RECORDABLE)}")
    if not body.get("parcel_id"):
        _unprocessable("missing_fields", "parcel_id is required")
    day = _parse_day(body.get("date"))
    error = validate_sowing_method(op_type, body)
    if error:
        _unprocessable("invalid_sowing_method", error)

    # Fields only the user can give are checked before reading anything; the crop
    # (and a planned variety) come from the plan the record lands on.
    _FROM_PLAN = ("cropType", "variety")
    missing = [f for f in REQUIRED_FIELDS[op_type] if f not in _FROM_PLAN and body.get(f) in (None, "")]
    if missing:
        _unprocessable("missing_fields", f"missing: {', '.join(missing)}")

    parcel_urn = normalize_parcel_urn(str(body["parcel_id"]))
    client = _orion(tenant_id)
    try:
        parcel, crops, ops = await _crop_data(client, parcel_urn)
        match = match_record(parcel_urn, crops, ops, op_type, day, _today(parcel))
        if not match.ok:
            raise HTTPException(status_code=409, detail={"code": match.reason})

        attrs = {k: body[k] for k in ("seedingRate", "sowingMethod", "harvestedWeight",
                                       "harvestDestination", "notes") if body.get(k) not in (None, "")}
        if op_type == "sowing":
            attrs["cropType"] = match.species
            attrs["variety"] = body.get("variety") or match.variety
        missing = [f for f in REQUIRED_FIELDS[op_type] if attrs.get(f) in (None, "")]
        if missing:
            _unprocessable("missing_fields", f"missing: {', '.join(missing)}")

        stamp = f"{day.isoformat()}T12:00:00Z"  # the day is the fact; noon keeps it in every time zone
        entity = await asyncio.to_thread(
            create_operation, tenant_id,
            parcel_id=parcel_urn, operation_type=op_type, work_order=f"REG-{day.isoformat()}",
            operator=user_id, data_source="manual", status="completed",
            startedAt=stamp, endedAt=stamp, **attrs,
        )
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
        return {"operation_id": entity.get("id"), "crop_id": match.crop_id, "species": match.species,
                "role": match.role, "campaign": match.campaign, "reconciled": reconciled}
    finally:
        await client.close()


def _cycle_view(cy, crops_by_id: dict) -> dict:
    d = cy.to_dict()
    crop = crops_by_id.get(cy.crop_id, {})
    variety = crop.get("variety")
    d["variety"] = variety.get("value") if isinstance(variety, dict) else variety
    open_ = cy.status not in _CLOSED
    d["can_sow"] = open_ and cy.start.provenance not in _FACTS
    d["can_harvest"] = open_ and cy.start.provenance in _FACTS and cy.end.provenance != "actual"
    return d


async def _parcel_view(tenant_id: str, parcel: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        client = _orion(tenant_id)
        try:
            full, crops, ops = await load_crop_data(client, parcel["id"])
            timeline = resolve_crop_cycles(parcel["id"], crops, ops, local_today(full))
            by_id = {c.get("id"): c for c in crops}
            cycles = [_cycle_view(cy, by_id) for cy in timeline.cycles]
            cycles = [c for c in cycles if c["can_sow"] or c["can_harvest"]]
            readable = True
        except Exception as exc:  # noqa: BLE001 — one unreadable parcel never hides the others
            logger.warning("record: parcel unreadable tenant=%s parcel=%s: %s", tenant_id, parcel.get("id"), exc)
            cycles, readable = [], False
        finally:
            await client.close()
    return {"id": parcel["id"], "name": parcel.get("name"), "area": parcel.get("area"),
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
    finally:
        await client.close()
    sem = asyncio.Semaphore(_CONCURRENCY)
    views = await asyncio.gather(*(_parcel_view(tenant_id, p, sem) for p in parcels))
    return {"parcels": sorted(views, key=lambda v: (v["name"] or v["id"]).lower())}
