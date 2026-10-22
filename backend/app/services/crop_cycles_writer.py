"""Crop-cycle writer: what is in the field, written back to the broker.

Field operations record the sowing and the harvest, so this module owns the
facts derived from them. The rule lives in the SDK (``crop_cycles``, owner
decision A: only a sown or declared crop is in the field); this module does the
writes, and only when they change, so its own notifications settle:

- ``actualPlantingDate`` / ``actualTerminationDate`` on the crop, from completed
  sowing and harvest/termination operations;
- ``hasAgriCrop`` and ``lastPlantedAt`` on the parcel for the crop in the field;
- removal of a parcel link that points to a crop that is still just a plan.
"""

from __future__ import annotations

import logging
from datetime import date

import httpx
from nkz_platform_sdk.crop_cycles import resolve_crop_cycles
from nkz_platform_sdk.crop_timeline import load_crop_data, local_today

logger = logging.getLogger(__name__)

_PAGE = 500
_CLOSED = ("harvested", "terminated")
_FACTS = ("actual", "declared")


def _val(attr):
    if isinstance(attr, dict):
        return attr.get("@value") or attr.get("object") or _val(attr.get("value"))
    return attr


def _date_prop(d: date) -> dict:
    return {"type": "Property", "value": {"@type": "Date", "@value": d.isoformat()}}


async def reconcile_parcel(client, tenant_id: str, parcel_urn: str, at: date | None = None) -> list:
    """Write the parcel's crop-cycle facts that changed. Returns what was written."""
    parcel, crops, ops = await load_crop_data(client, parcel_urn)
    tl = resolve_crop_cycles(parcel_urn, crops, ops, at or local_today(parcel))
    by_id = {c.get("id"): c for c in crops}
    written = []
    for cy in tl.cycles:
        crop = by_id.get(cy.crop_id, {})
        for boundary, attr in ((cy.start, "actualPlantingDate"), (cy.end, "actualTerminationDate")):
            if boundary.provenance == "actual" and str(_val(crop.get(attr)) or "")[:10] != boundary.date.isoformat():
                await client.append_entity_attrs(cy.crop_id, {attr: _date_prop(boundary.date)})
                written.append((cy.crop_id, attr))
    cur = tl.current
    link_key = "hasAgriCrop" if parcel.get("hasAgriCrop") is not None else (
        "refAgriCrop" if parcel.get("refAgriCrop") is not None else None)
    linked = _val(parcel.get(link_key)) if link_key else None
    if cur is None and linked:
        # A link to a crop that is still just a plan (not closed) was never true:
        # remove it. A link to a crop this parcel's cycles do not include is left alone.
        target = next((cy for cy in tl.cycles if cy.crop_id == linked), None)
        if target and target.start.provenance == "planned" and target.status not in _CLOSED:
            try:
                await client.delete_entity_attr(parcel_urn, link_key)
                written.append((parcel_urn, f"-{link_key}"))
            except httpx.HTTPStatusError as e:
                if e.response is None or e.response.status_code != 404:
                    raise
    if cur:
        if linked != cur.crop_id:
            await client.append_entity_attrs(
                parcel_urn, {"hasAgriCrop": {"type": "Relationship", "object": cur.crop_id}})
            written.append((parcel_urn, "hasAgriCrop"))
        if cur.start.provenance in _FACTS:
            stamp = f"{cur.start.date.isoformat()}T00:00:00Z"
            if str(_val(parcel.get("lastPlantedAt")) or "") != stamp:
                await client.append_entity_attrs(parcel_urn, {"lastPlantedAt": {
                    "type": "Property", "value": {"@type": "DateTime", "@value": stamp}}})
                written.append((parcel_urn, "lastPlantedAt"))
    if written:
        logger.info("crop-cycle reconcile tenant=%s parcel=%s wrote=%s", tenant_id, parcel_urn, written)
    return written


async def list_parcels(client) -> list:
    """Every AgriParcel id of the client's tenant, paged. No attrs filter: attrs
    selects entities that HAVE those attributes, and 'id' is not an attribute."""
    ids, offset = [], 0
    while True:
        page = await client.query_entities(type="AgriParcel", limit=_PAGE, offset=offset, options="keyValues")
        ids.extend(e["id"] for e in page or [] if e.get("id"))
        if not page or len(page) < _PAGE:
            return ids
        offset += _PAGE


def parcels_in_notification(entities: list) -> set:
    """Parcels touched by an AgriCrop / AgriParcelOperation notification."""
    out = set()
    for e in entities or []:
        if e.get("type") not in ("AgriCrop", "AgriParcelOperation"):
            continue
        p = _val(e.get("hasAgriParcel")) or _val(e.get("refAgriParcel"))
        if isinstance(p, str) and p:
            out.add(p)
    return out
