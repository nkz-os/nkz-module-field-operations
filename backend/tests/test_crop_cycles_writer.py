"""Crop-cycle writer: reconcile a parcel from its crops and field operations.

Rule (SDK crop_cycles, owner decision A): only a sown or declared crop is in the
field. The writer links it, stamps the facts, and removes a link that points to
a crop that is still just a plan. It writes only on change, so its own
notifications settle.
"""
from datetime import date

import httpx
import pytest

from app.services import crop_cycles_writer as w

P = "urn:ngsi-ld:AgriParcel:p1"
AT = date(2026, 10, 9)


def _404(url="x"):
    req = httpx.Request("DELETE", url)
    return httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))


class FakeOrion:
    def __init__(self, parcel=None, crops=(), ops=(), parcels=None, fail=False):
        self.parcel = parcel if parcel is not None else {"id": P, "type": "AgriParcel"}
        self.crops, self.ops = list(crops), list(ops)
        self.parcels = parcels
        self.fail = fail
        self.writes, self.deletes = [], []

    async def get_entity(self, eid, options=None):
        if self.fail:
            raise httpx.ConnectError("down")
        if eid != P:
            raise _404()
        return self.parcel

    async def query_entities(self, type=None, q=None, limit=100, offset=0, attrs=None, options=None):
        if type == "AgriParcel":
            ids = self.parcels or []
            return [{"id": i} for i in ids[offset:offset + limit]]
        return self.crops if type == "AgriCrop" else self.ops

    async def append_entity_attrs(self, eid, attrs, overwrite=True):
        self.writes.append((eid, attrs))
        target = self.parcel if eid == P else next(c for c in self.crops if c["id"] == eid)
        for k, v in attrs.items():
            target[k] = v.get("object") or v.get("value")

    async def delete_entity_attr(self, eid, attr):
        self.deletes.append((eid, attr))
        target = self.parcel if eid == P else next(c for c in self.crops if c["id"] == eid)
        if attr not in target:
            raise _404()
        del target[attr]


CROP = {"id": "urn:ngsi-ld:AgriCrop:t:a", "type": "AgriCrop", "refAgriParcel": P, "status": "active",
        "plantingDate": "2026-03-01", "harvestDate": "2026-11-30"}
DECLARED = {**CROP, "plantingDateSource": "manual"}
PLANNED = {**CROP, "status": "planned"}
SOW = {"id": "urn:ngsi-ld:AgriParcelOperation:s1", "type": "AgriParcelOperation", "hasAgriParcel": P,
       "operationType": "sowing", "status": "completed", "endedAt": "2026-03-12T09:00:00Z"}


@pytest.mark.asyncio
async def test_reconcile_writes_actuals_and_parcel_facts():
    fake = FakeOrion(crops=[dict(CROP)], ops=[dict(SOW)])
    written = await w.reconcile_parcel(fake, "t", P, AT)
    assert (CROP["id"], "actualPlantingDate") in written
    assert (P, "hasAgriCrop") in written and (P, "lastPlantedAt") in written
    crop_attrs = dict(fake.writes)[CROP["id"]]
    assert crop_attrs["actualPlantingDate"]["value"] == {"@type": "Date", "@value": "2026-03-12"}


@pytest.mark.asyncio
async def test_reconcile_is_idempotent():
    fake = FakeOrion(crops=[dict(CROP)], ops=[dict(SOW)])
    await w.reconcile_parcel(fake, "t", P, AT)
    assert await w.reconcile_parcel(fake, "t", P, AT) == []


@pytest.mark.asyncio
async def test_reconcile_planned_start_links_nothing():
    fake = FakeOrion(crops=[dict(PLANNED)])
    assert await w.reconcile_parcel(fake, "t", P, AT) == []


@pytest.mark.asyncio
async def test_reconcile_removes_a_link_to_a_planned_only_crop():
    fake = FakeOrion(parcel={"id": P, "type": "AgriParcel", "hasAgriCrop": CROP["id"]}, crops=[dict(PLANNED)])
    written = await w.reconcile_parcel(fake, "t", P, AT)
    assert fake.deletes == [(P, "hasAgriCrop")] and (P, "-hasAgriCrop") in written
    assert await w.reconcile_parcel(fake, "t", P, AT) == []


@pytest.mark.asyncio
async def test_reconcile_removes_the_alias_key_orion_returned():
    fake = FakeOrion(parcel={"id": P, "type": "AgriParcel", "refAgriCrop": CROP["id"]}, crops=[dict(PLANNED)])
    await w.reconcile_parcel(fake, "t", P, AT)
    assert fake.deletes == [(P, "refAgriCrop")]


@pytest.mark.asyncio
async def test_reconcile_removes_a_link_to_an_assigned_but_unsown_crop():
    """The retired crop-assignment shape (active + plantingDate, no source, no sowing) is a plan."""
    fake = FakeOrion(parcel={"id": P, "type": "AgriParcel", "hasAgriCrop": CROP["id"]}, crops=[dict(CROP)])
    await w.reconcile_parcel(fake, "t", P, AT)
    assert fake.deletes == [(P, "hasAgriCrop")]


@pytest.mark.asyncio
async def test_reconcile_keeps_a_link_it_cannot_judge():
    other = "urn:ngsi-ld:AgriCrop:t:elsewhere"
    fake = FakeOrion(parcel={"id": P, "type": "AgriParcel", "hasAgriCrop": other}, crops=[dict(PLANNED)])
    await w.reconcile_parcel(fake, "t", P, AT)
    assert fake.deletes == []


@pytest.mark.asyncio
async def test_reconcile_keeps_a_link_to_a_closed_crop():
    harvested = {**CROP, "status": "harvested"}
    fake = FakeOrion(parcel={"id": P, "type": "AgriParcel", "hasAgriCrop": CROP["id"]}, crops=[harvested])
    await w.reconcile_parcel(fake, "t", P, AT)
    assert fake.deletes == []


@pytest.mark.asyncio
async def test_reconcile_declared_sowing_links_and_stamps():
    fake = FakeOrion(crops=[dict(DECLARED)])
    written = await w.reconcile_parcel(fake, "t", P, AT)
    assert (P, "hasAgriCrop") in written and (P, "lastPlantedAt") in written


@pytest.mark.asyncio
async def test_list_parcels_pages_without_attrs_filter():
    ids = [f"urn:ngsi-ld:AgriParcel:{i}" for i in range(1203)]
    assert await w.list_parcels(FakeOrion(parcels=ids)) == ids


def test_parcels_in_notification():
    entities = [
        {"type": "AgriCrop", "hasAgriParcel": {"type": "Relationship", "object": P}},
        {"type": "AgriParcelOperation", "refAgriParcel": "urn:ngsi-ld:AgriParcel:p2"},
        {"type": "WeatherObserved", "hasAgriParcel": "urn:ngsi-ld:AgriParcel:p3"},
        {"type": "AgriCrop"},
    ]
    assert w.parcels_in_notification(entities) == {P, "urn:ngsi-ld:AgriParcel:p2"}


@pytest.mark.asyncio
async def test_reconcile_with_the_broker_down_writes_nothing():
    from nkz_platform_sdk.crop_timeline import CropDataUnavailable

    fake = FakeOrion(parcel={"id": P, "type": "AgriParcel", "hasAgriCrop": CROP["id"]},
                     crops=[dict(PLANNED)], fail=True)
    with pytest.raises(CropDataUnavailable):
        await w.reconcile_parcel(fake, "t", P, AT)
    assert fake.writes == [] and fake.deletes == []
