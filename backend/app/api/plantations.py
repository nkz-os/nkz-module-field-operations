"""Declare an existing perennial plantation on a parcel.

Mounted behind the gateway identity. The entity rules live in
``services.plantation``; this module reads the parcel's cycles and writes.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from nkz_platform_sdk.crop_cycles import resolve_crop_cycles
from nkz_platform_sdk.crop_timeline import local_today, normalize_parcel_urn

from .. import config
from ..services import plantation as pl
from ..services.crop_cycles_writer import reconcile_parcel
from .record import _PARCEL, _crop_data, _orion

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/field-operations", tags=["plantations"])


def _today(parcel: dict):
    return local_today(parcel)


def _raise(exc: pl.PlantationError):
    raise HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": exc.detail})


@router.post("/parcels/{parcel_id}/plantations", status_code=201)
async def declare_plantation(request: Request, parcel_id: str, body: dict):
    tenant_id = request.state.tenant_id
    if not _PARCEL.match(parcel_id):
        raise HTTPException(status_code=422, detail={"code": "invalid_parcel", "detail": "not a parcel id"})
    parcel_urn = normalize_parcel_urn(parcel_id)
    client = _orion(tenant_id)
    try:
        parcel, crops, ops = await _crop_data(client, parcel_urn)
        today = _today(parcel)
        try:
            eppo = pl.parse_species(body.get("eppo"))
            planting = pl.parse_planting(body.get("planting_year"), body.get("planting_date"), today)
        except pl.PlantationError as exc:
            _raise(exc)
        variety = body.get("variety")
        variety = variety.strip() if isinstance(variety, str) and variety.strip() else None
        crop_id = pl.plantation_crop_id(tenant_id, parcel_urn, planting.year)
        if any(c.get("id") == crop_id for c in crops):
            raise HTTPException(status_code=409, detail={"code": "already_declared", "crop_id": crop_id})
        current = resolve_crop_cycles(parcel_urn, crops, ops, today).current
        if current is not None and current.role == "main_crop":
            raise HTTPException(status_code=409, detail={"code": "parcel_has_current_crop",
                                                         "crop_id": current.crop_id})
        try:
            await client.create_entity(pl.build_plantation(tenant_id, parcel_urn, eppo, planting, variety))
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 409:
                raise HTTPException(status_code=409, detail={"code": "already_declared", "crop_id": crop_id})
            logger.error("plantation: write failed tenant=%s parcel=%s crop=%s: %s",
                         tenant_id, parcel_urn, crop_id, exc)
            raise HTTPException(status_code=503, detail={"code": "store_unavailable", "detail": str(exc)})
        except (httpx.HTTPError, RuntimeError) as exc:
            logger.error("plantation: write failed tenant=%s parcel=%s crop=%s: %s",
                         tenant_id, parcel_urn, crop_id, exc)
            raise HTTPException(status_code=503, detail={"code": "store_unavailable", "detail": str(exc)})
        logger.info("plantation: tenant=%s parcel=%s crop=%s eppo=%s planting=%s",
                    tenant_id, parcel_urn, crop_id, eppo, planting.isoformat())
        if config.CROP_CYCLES_WRITER_ENABLED:
            # Links hasAgriCrop at once; the notification and the daily sweep do it again.
            try:
                await reconcile_parcel(client, tenant_id, parcel_urn)
            except Exception as exc:  # noqa: BLE001 — the declaration stands; the sweep catches up
                logger.warning("plantation: reconcile failed tenant=%s parcel=%s: %s", tenant_id, parcel_urn, exc)
        return {"crop_id": crop_id}
    finally:
        await client.close()
