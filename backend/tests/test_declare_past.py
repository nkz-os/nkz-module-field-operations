"""POST/GET /parcels/{id}/declared-crops: declare a past crop (campaign + species, no dates)."""
import asyncio
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import declared_crops as route
from app.api import record as record_route
from app.main import app
from app.services import crop_cycles_writer as writer
from app.services import declare_past as dp

P = "urn:ngsi-ld:AgriParcel:p1"
H = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u1"}
URL = "/api/field-operations/parcels/p1/declared-crops"
IRI = "https://nkz-os.org/ns/declaredCampaign"  # what Orion returns for nkz:declaredCampaign
TODAY = date(2026, 11, 20)
OWN = "urn:ngsi-ld:AgriCrop:tenant-a:p1:declared-2024"

DATED = {"id": "urn:ngsi-ld:AgriCrop:tenant-a:p1:2025:1", "type": "AgriCrop", "hasAgriParcel": P,
         "status": "harvested", "cropRole": "main_crop", "species": "ZEAMX",
         "plantingDate": "2025-04-20", "terminationDate": "2025-10-05"}


def declared(campaign, species="TRZAX", cid=None):
    return {"id": cid or f"urn:ngsi-ld:AgriCrop:tenant-a:p1:declared-{campaign}", "type": "AgriCrop",
            "hasAgriParcel": P, "status": "harvested", "cropRole": "main_crop", "species": species,
            IRI: campaign}


class FakeOrion:
    def __init__(self, crops=(), create_error=None):
        self.parcel = {"id": P, "type": "AgriParcel", "name": "Soto Alto"}
        self.crops = list(crops)
        self.created, self.updated, self.appended, self.deleted = [], [], [], []
        self.create_error = create_error

    async def get_entity(self, eid, options=None):
        return self.parcel

    async def query_entities(self, type=None, q=None, limit=100, offset=0, attrs=None, options=None):
        return self.crops if type == "AgriCrop" and offset == 0 else []

    async def create_entity(self, entity):
        if self.create_error:
            raise self.create_error
        self.created.append(entity)
        return {"id": entity["id"], "status": "created"}

    async def update_entity_attrs(self, eid, attrs):
        self.updated.append((eid, attrs))

    async def append_entity_attrs(self, eid, attrs, overwrite=True):
        self.appended.append((eid, attrs))

    async def delete_entity(self, eid):
        self.deleted.append(eid)

    async def close(self):
        pass


@pytest.fixture
def env(monkeypatch):
    state = {"orion": FakeOrion()}
    monkeypatch.setattr(record_route, "_orion", lambda tenant: state["orion"])
    monkeypatch.setattr(route, "_orion", lambda tenant: state["orion"])
    monkeypatch.setattr(route, "_today", lambda parcel: TODAY)
    return state


def post(body):
    return TestClient(app).post(URL, headers=H, json=body)


def _no_null(value):
    if isinstance(value, dict):
        return all(_no_null(v) for v in value.values())
    return value is not None and value != "urn:ngsi-ld:null"


def test_creates_the_closed_dateless_crop(env):
    r = post({"campaign": 2024, "eppo": "TRZAX"})
    assert r.status_code == 201 and r.json() == {"crop_id": OWN}
    (e,) = env["orion"].created
    assert e["id"] == OWN and e["type"] == "AgriCrop"
    assert e["status"]["value"] == "harvested" and e["cropRole"]["value"] == "main_crop"
    assert e["species"]["value"] == "TRZAX" and e["nkz:declaredCampaign"] == {"type": "Property", "value": 2024}
    assert e["hasAgriParcel"] == {"type": "Relationship", "object": P}
    assert not any("date" in k.lower() or k.endswith("At") for k in e)
    assert _no_null(e)
    assert env["orion"].appended == []  # nothing on the parcel


def test_species_is_normalised_to_upper_case(env):
    assert post({"campaign": 2024, "eppo": " trzax "}).status_code == 201
    assert env["orion"].created[0]["species"]["value"] == "TRZAX"


@pytest.mark.parametrize("today,campaign,ok", [
    (date(2026, 11, 20), 2026, True), (date(2026, 11, 20), 2027, False),
    (date(2026, 7, 1), 2026, True), (date(2026, 6, 30), 2026, False),
    (date(2026, 3, 1), 2026, False), (date(2026, 3, 1), 2025, True),
])
def test_campaign_past_follows_the_july_rollover(env, monkeypatch, today, campaign, ok):
    monkeypatch.setattr(route, "_today", lambda parcel: today)
    r = post({"campaign": campaign, "eppo": "TRZAX"})
    if ok:
        assert r.status_code == 201
    else:
        assert r.status_code == 422 and r.json()["detail"]["code"] == "campaign_not_past"
        assert env["orion"].created == []


@pytest.mark.parametrize("campaign", ["2024", 2024.5, True, None, 12])
def test_malformed_campaign_is_422(env, campaign):
    r = post({"campaign": campaign, "eppo": "TRZAX"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_campaign"


@pytest.mark.parametrize("eppo", ["fallow", "", None, "TR", "WHEA", "TRZAXXX", 5, "TRZ AX", "TRZ-X"])
def test_invalid_species_is_422(env, eppo):
    r = post({"campaign": 2024, "eppo": eppo})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_species"
    assert env["orion"].created == []


def test_campaign_with_a_dated_cycle_is_409(env):
    env["orion"] = FakeOrion([DATED])
    r = post({"campaign": 2025, "eppo": "TRZAX"})
    assert r.status_code == 409 and r.json()["detail"]["crop_id"] == DATED["id"]
    assert env["orion"].created == [] and env["orion"].updated == []


def test_a_dated_cycle_of_another_campaign_does_not_block(env):
    env["orion"] = FakeOrion([DATED])
    assert post({"campaign": 2024, "eppo": "TRZAX"}).status_code == 201


OLIVE = {"id": "urn:ngsi-ld:AgriCrop:tenant-a:p1:plantation-2000", "type": "AgriCrop", "hasAgriParcel": P,
         "status": "active", "cropRole": "main_crop", "species": "OLVEU", "cropLifecycle": "perennial",
         "plantingDate": "2000-01-01", "plantingDateSource": "manual"}


def test_a_living_perennial_blocks_a_later_campaign(env):
    env["orion"] = FakeOrion([OLIVE])
    r = post({"campaign": 2024, "eppo": "TRZAX"})
    assert r.status_code == 409 and r.json()["detail"]["crop_id"] == OLIVE["id"]
    assert env["orion"].created == []


def test_a_perennial_does_not_block_a_campaign_before_its_planting(env):
    env["orion"] = FakeOrion([OLIVE])
    assert post({"campaign": 1998, "eppo": "TRZAX"}).status_code == 201


def test_redeclaring_updates_species_on_the_same_entity(env):
    env["orion"] = FakeOrion([declared(2024, "TRZAX")])
    r = post({"campaign": 2024, "eppo": "HORVX"})
    assert r.status_code == 201 and r.json() == {"crop_id": OWN}
    assert env["orion"].created == []
    assert env["orion"].updated == [(OWN, {"species": {"type": "Property", "value": "HORVX"}})]
    assert _no_null(env["orion"].updated[0][1])


def test_create_race_falls_back_to_update(env):
    req = httpx.Request("POST", "http://orion")
    env["orion"] = FakeOrion(create_error=httpx.HTTPStatusError(
        "409", request=req, response=httpx.Response(409, request=req)))
    assert post({"campaign": 2024, "eppo": "HORVX"}).status_code == 201
    assert env["orion"].updated[0][0] == OWN


def test_store_failure_is_503(env):
    env["orion"] = FakeOrion(create_error=httpx.ConnectError("down"))
    r = post({"campaign": 2024, "eppo": "HORVX"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "store_unavailable"


def test_get_lists_declared_crops_only(env):
    env["orion"] = FakeOrion([declared(2024, "HORVX"), declared(2023, "TRZAX"), DATED])
    r = TestClient(app).get(URL, headers=H)
    assert r.status_code == 200
    assert r.json() == [
        {"campaign": 2023, "eppo": "TRZAX", "crop_id": "urn:ngsi-ld:AgriCrop:tenant-a:p1:declared-2023"},
        {"campaign": 2024, "eppo": "HORVX", "crop_id": OWN},
    ]


def test_declared_crop_resolves_as_previous_for_the_sdk(env):
    from nkz_platform_sdk.crop_cycles import resolve_crop_cycles
    e = declared(2025, "TRZAX")
    assert resolve_crop_cycles(P, [e], [], TODAY).previous.species == "TRZAX"


def test_reconcile_never_links_a_declared_crop(env):
    orion = FakeOrion([declared(2025, "TRZAX"), declared(2024, "HORVX")])
    written = asyncio.run(writer.reconcile_parcel(orion, "tenant-a", P, TODAY))
    assert written == [] and orion.appended == []
    assert "hasAgriCrop" not in orion.parcel and "lastPlantedAt" not in orion.parcel


def test_ids_are_per_parcel_and_campaign():
    assert dp.declared_crop_id("t", "urn:ngsi-ld:AgriParcel:p9", 2020) == "urn:ngsi-ld:AgriCrop:t:p9:declared-2020"


def test_five_char_code_with_digit_is_accepted(env):
    assert post({"campaign": 2024, "eppo": "1ABCD"}).status_code == 201
    assert env["orion"].created[0]["species"]["value"] == "1ABCD"


def test_parcels_sharing_a_last_segment_get_distinct_ids(env):
    x, y = "urn:ngsi-ld:AgriParcel:x:p1", "urn:ngsi-ld:AgriParcel:y:p1"
    assert dp.declared_crop_id("t", x, 2020) != dp.declared_crop_id("t", y, 2020)
    other = declared(2024, "TRZAX", cid=dp.declared_crop_id("tenant-a", x, 2024))
    other["hasAgriParcel"] = x
    env["orion"] = FakeOrion([other])
    r = TestClient(app).post("/api/field-operations/parcels/y:p1/declared-crops", headers=H,
                             json={"campaign": 2024, "eppo": "HORVX"})
    assert r.status_code == 201
    assert r.json()["crop_id"] == "urn:ngsi-ld:AgriCrop:tenant-a:y:p1:declared-2024"
    assert env["orion"].updated == [] and len(env["orion"].created) == 1


def test_planned_never_sown_crop_does_not_block_a_declaration(env):
    planned = {"id": "urn:ngsi-ld:AgriCrop:tenant-a:p1:plan", "type": "AgriCrop", "hasAgriParcel": P,
               "status": "pending", "cropRole": "main_crop", "species": "ZEAMX",
               "plannedPlantingDate": "2025-04-20", "plannedHarvestDate": "2025-10-05"}
    env["orion"] = FakeOrion([planned])
    assert post({"campaign": 2025, "eppo": "TRZAX"}).status_code == 201


DEL = URL + "/2024"


def delete(url=DEL, headers=H):
    return TestClient(app).delete(url, headers=headers)


def test_delete_removes_the_declaration(env):
    env["orion"] = FakeOrion([declared(2024)])
    r = delete()
    assert r.status_code == 204 and env["orion"].deleted == [OWN]


def test_delete_without_declaration_is_404(env):
    assert delete().status_code == 404 and env["orion"].deleted == []


def test_delete_never_touches_a_dated_crop(env):
    env["orion"] = FakeOrion([DATED])
    assert TestClient(app).delete(URL + "/2025", headers=H).status_code == 404
    assert env["orion"].deleted == []
    # even when a dated crop carries the declared id
    clash = dict(DATED, id=dp.declared_crop_id("tenant-a", P, 2025))
    env["orion"] = FakeOrion([clash])
    assert TestClient(app).delete(URL + "/2025", headers=H).status_code == 404
    assert env["orion"].deleted == []


def test_delete_takes_the_tenant_from_identity(env):
    other = declared(2024, cid="urn:ngsi-ld:AgriCrop:tenant-b:p1:declared-2024")
    env["orion"] = FakeOrion([other])
    assert delete().status_code == 404 and env["orion"].deleted == []
    r = delete(headers={"X-Tenant-ID": "tenant-b", "X-User-ID": "u1"})
    assert r.status_code == 204 and env["orion"].deleted == [other["id"]]


def test_delete_store_failure_is_503(env):
    env["orion"] = FakeOrion([declared(2024)])

    async def boom(eid):
        raise httpx.ConnectError("down")
    env["orion"].delete_entity = boom
    assert delete().status_code == 503
