"""Declare the crop a parcel grew in a past campaign (campaign + species, no dates).

Mounted behind the gateway identity. The entity rules live in
``services.declare_past``; this module reads the parcel's cycles and writes.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from nkz_platform_sdk.crop_cycles import resolve_crop_cycles
from nkz_platform_sdk.crop_timeline import local_today, normalize_parcel_urn

from ..services import declare_past as dp
from .record import _PARCEL, _crop_data, _orion

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/field-operations", tags=["declared-crops"])


def _today(parcel: dict):
    return local_today(parcel)


def _parcel_urn(parcel_id: str) -> str:
    if not _PARCEL.match(parcel_id):
        raise HTTPException(status_code=422, detail={"code": "invalid_parcel", "detail": "not a parcel id"})
    return normalize_parcel_urn(parcel_id)


def _raise(exc: dp.DeclareError):
    raise HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": exc.detail})


@router.post("/parcels/{parcel_id}/declared-crops", status_code=201)
async def declare_past_crop(request: Request, parcel_id: str, body: dict):
    tenant_id = request.state.tenant_id
    parcel_urn = _parcel_urn(parcel_id)
    client = _orion(tenant_id)
    try:
        parcel, crops, ops = await _crop_data(client, parcel_urn)
        try:
            eppo = dp.parse_species(body.get("eppo"))
            campaign = dp.parse_campaign(body.get("campaign"), _today(parcel))
        except dp.DeclareError as exc:
            _raise(exc)
        crop_id = dp.declared_crop_id(tenant_id, parcel_urn, campaign)
        timeline = resolve_crop_cycles(parcel_urn, crops, ops, _today(parcel))
        other = dp.dated_conflict(timeline.cycles, campaign, crop_id)
        if other:
            raise HTTPException(status_code=409, detail={"code": "campaign_has_dated_crop", "crop_id": other})
        try:
            if any(c.get("id") == crop_id for c in crops):
                await client.update_entity_attrs(crop_id, dp.species_patch(eppo))
            else:
                try:
                    await client.create_entity(dp.build_entity(tenant_id, parcel_urn, campaign, eppo))
                except httpx.HTTPStatusError as exc:
                    if exc.response is None or exc.response.status_code != 409:
                        raise
                    # Declared at the same moment by another request: the same entity, update it.
                    await client.update_entity_attrs(crop_id, dp.species_patch(eppo))
        except (httpx.HTTPError, RuntimeError) as exc:
            logger.error("declare-past: write failed tenant=%s parcel=%s crop=%s: %s",
                         tenant_id, parcel_urn, crop_id, exc)
            raise HTTPException(status_code=503, detail={"code": "store_unavailable", "detail": str(exc)})
        logger.info("declare-past: tenant=%s parcel=%s crop=%s campaign=%s eppo=%s",
                    tenant_id, parcel_urn, crop_id, campaign, eppo)
        return {"crop_id": crop_id}
    finally:
        await client.close()


@router.delete("/parcels/{parcel_id}/declared-crops/{campaign}", status_code=204)
async def delete_declared_crop(request: Request, parcel_id: str, campaign: int):
    tenant_id = request.state.tenant_id
    parcel_urn = _parcel_urn(parcel_id)
    crop_id = dp.declared_crop_id(tenant_id, parcel_urn, campaign)
    client = _orion(tenant_id)
    try:
        parcel, crops, ops = await _crop_data(client, parcel_urn)
        timeline = resolve_crop_cycles(parcel_urn, crops, ops, _today(parcel))
        if not dp.declared_only_id(timeline.cycles, crop_id):
            raise HTTPException(status_code=404, detail={"code": "declaration_not_found"})
        try:
            await client.delete_entity(crop_id)
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                raise HTTPException(status_code=404, detail={"code": "declaration_not_found"})
            logger.error("declare-past: delete failed tenant=%s parcel=%s crop=%s: %s",
                         tenant_id, parcel_urn, crop_id, exc)
            raise HTTPException(status_code=503, detail={"code": "store_unavailable", "detail": str(exc)})
        except (httpx.HTTPError, RuntimeError) as exc:
            logger.error("declare-past: delete failed tenant=%s parcel=%s crop=%s: %s",
                         tenant_id, parcel_urn, crop_id, exc)
            raise HTTPException(status_code=503, detail={"code": "store_unavailable", "detail": str(exc)})
        logger.info("declare-past: deleted tenant=%s parcel=%s crop=%s campaign=%s",
                    tenant_id, parcel_urn, crop_id, campaign)
    finally:
        await client.close()


@router.get("/parcels/{parcel_id}/declared-crops")
async def list_declared_crops(request: Request, parcel_id: str) -> list[dict]:
    tenant_id = request.state.tenant_id
    parcel_urn = _parcel_urn(parcel_id)
    client = _orion(tenant_id)
    try:
        parcel, crops, ops = await _crop_data(client, parcel_urn)
        timeline = resolve_crop_cycles(parcel_urn, crops, ops, _today(parcel))
        return dp.list_declared(timeline.cycles)
    finally:
        await client.close()
