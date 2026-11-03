"""POST /parcels/{id}/plantations: declare an existing perennial plantation."""
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import plantations as route
from app.api import record as record_route
from app.main import app
from app.services import plantation as pl
from app.services.record import match_record

P = "urn:ngsi-ld:AgriParcel:p1"
H = {"X-Tenant-ID": "acme", "X-User-ID": "u1"}
URL = "/api/field-operations/parcels/p1/plantations"
TODAY = date(2026, 11, 20)
OWN = "urn:ngsi-ld:AgriCrop:acme:p1:plantation-2000"


class FakeOrion:
    def __init__(self, crops=(), ops=(), create_error=None):
        self.parcel = {"id": P, "type": "AgriParcel", "name": "Parcel A"}
        self.crops, self.ops, self.create_error = list(crops), list(ops), create_error
        self.created = []

    async def get_entity(self, eid, options=None):
        return self.parcel

    async def query_entities(self, type=None, q=None, limit=100, offset=0, attrs=None, options=None):
        if offset:
            return []
        return self.crops if type == "AgriCrop" else self.ops

    async def create_entity(self, entity):
        if self.create_error:
            raise self.create_error
        self.created.append(entity)
        return {"id": entity["id"]}

    async def close(self):
        pass


@pytest.fixture
def env(monkeypatch):
    state = {"orion": FakeOrion(), "reconciled": []}
    monkeypatch.setattr(record_route, "_orion", lambda tenant: state["orion"])
    monkeypatch.setattr(route, "_orion", lambda tenant: state["orion"])
    monkeypatch.setattr(route, "_today", lambda parcel: TODAY)

    async def fake_reconcile(client, tenant_id, parcel):
        state["reconciled"].append((tenant_id, parcel))
        return []

    monkeypatch.setattr(route, "reconcile_parcel", fake_reconcile)
    monkeypatch.setattr(route.config, "CROP_CYCLES_WRITER_ENABLED", True)
    return state


def post(body):
    return TestClient(app).post(URL, headers=H, json=body)


def test_build_plantation_shape():
    e = pl.build_plantation("acme", P, "OLVEU", date(2000, 1, 1), "Arbequina")
    assert e["id"] == OWN and e["type"] == "AgriCrop"
    assert e["hasAgriParcel"] == {"type": "Relationship", "object": P}
    assert e["cropRole"]["value"] == "main_crop" and e["cropLifecycle"]["value"] == "perennial"
    assert e["status"]["value"] == "active" and e["species"]["value"] == "OLVEU"
    assert e["plantingDate"]["value"] == {"@type": "Date", "@value": "2000-01-01"}
    assert e["plantingDateSource"]["value"] == "manual"
    assert e["variety"]["value"] == "Arbequina"
    assert "harvestDate" not in e and "expectedTerminationDate" not in e
    assert "variety" not in pl.build_plantation("acme", P, "OLVEU", date(2000, 1, 1), None)


def test_crop_id_forms():
    assert pl.plantation_crop_id("acme", P, 2000) == OWN
    assert pl.plantation_crop_id("acme", "urn:ngsi-ld:AgriParcel:acme:p1", 2000) == OWN
    # Only the tenant prefix is dropped; other ':' stay so ids remain per parcel.
    assert pl.plantation_crop_id("acme", "urn:ngsi-ld:AgriParcel:z:p1", 2000) == \
        "urn:ngsi-ld:AgriCrop:acme:z:p1:plantation-2000"


def test_woody_list_is_the_frozen_ten():
    assert pl.WOODY_EPPO == frozenset("VITVI OLVEU PRNDU PIAVE MABSD PYUCO PRNPS PRNAR PRNDO PRNAV".split())


def test_declare_plantation_201_and_reconciles(env):
    r = post({"eppo": "olveu", "planting_year": 2000, "variety": "Arbequina"})
    assert r.status_code == 201 and r.json() == {"crop_id": OWN}
    (e,) = env["orion"].created
    assert e["species"]["value"] == "OLVEU" and e["plantingDate"]["value"]["@value"] == "2000-01-01"
    assert env["reconciled"] == [("acme", P)]


def test_explicit_planting_date_is_kept(env):
    assert post({"eppo": "OLVEU", "planting_year": 2000, "planting_date": "2000-03-15"}).status_code == 201
    assert env["orion"].created[0]["plantingDate"]["value"]["@value"] == "2000-03-15"


def test_declare_plantation_refused_when_current_crop(env):
    env["orion"].crops = [{"id": "urn:ngsi-ld:AgriCrop:acme:p1:other", "type": "AgriCrop", "hasAgriParcel": P,
                           "status": "active", "cropRole": "main_crop", "species": "OLVEU",
                           "cropLifecycle": "perennial", "plantingDate": "1995-01-01",
                           "plantingDateSource": "manual"}]
    r = post({"eppo": "OLVEU", "planting_year": 2000})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "parcel_has_current_crop"
    assert env["orion"].created == []


def test_declare_plantation_twice_409(env):
    env["orion"].create_error = httpx.HTTPStatusError(
        "dup", request=httpx.Request("POST", "http://x"), response=httpx.Response(409))
    r = post({"eppo": "OLVEU", "planting_year": 2000})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_declared"


def test_declare_existing_id_409_without_write(env):
    env["orion"].crops = [pl.build_plantation("acme", P, "OLVEU", date(2000, 1, 1), None)]
    r = post({"eppo": "OLVEU", "planting_year": 2000})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_declared"
    assert env["orion"].created == []


def test_declare_plantation_rejects_annual_species(env):
    r = post({"eppo": "HORVU", "planting_year": 2000})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_species"


@pytest.mark.parametrize("year", [1899, 2027, "2000", None, True, 2000.5])
def test_invalid_year_is_422(env, year):
    r = post({"eppo": "OLVEU", "planting_year": year})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_year"


def test_future_date_is_422(env):
    r = post({"eppo": "OLVEU", "planting_year": 2026, "planting_date": "2026-12-01"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "future_date"


def test_current_year_without_day_is_allowed(env):
    assert post({"eppo": "OLVEU", "planting_year": 2026}).status_code == 201


@pytest.mark.parametrize("day", ["nope", "1999-03-01"])
def test_bad_or_mismatched_date_is_422(env, day):
    r = post({"eppo": "OLVEU", "planting_year": 2000, "planting_date": day})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_date"


def test_store_failure_is_503(env):
    env["orion"].create_error = httpx.ConnectError("down")
    r = post({"eppo": "OLVEU", "planting_year": 2000})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "store_unavailable"


def test_plantation_then_harvest_records(env):
    entity = pl.build_plantation("acme", P, "OLVEU", date(2000, 1, 1), None)
    m = match_record(P, [entity], [], "harvesting", date(2026, 11, 20), date(2026, 11, 20))
    assert m.ok and m.crop_id == OWN and m.harvest_campaign == "2026"


WHEAT = {"id": "urn:ngsi-ld:AgriCrop:acme:p1:wheat", "type": "AgriCrop", "hasAgriParcel": P, "status": "planned",
         "cropRole": "main_crop", "species": "TRZAX", "sowingWindowStart": "2023-10-15",
         "expectedTerminationDate": "2024-07-31"}


def _wheat_ops():
    def op(n, kind, day):
        return {"id": f"urn:ngsi-ld:AgriParcelOperation:{n}", "type": "AgriParcelOperation", "operationType": kind,
                "status": "completed", "endedAt": f"{day}T12:00:00Z", "hasAgriParcel": P}
    return [op("w1", "sowing", "2023-11-10"), op("w2", "harvesting", "2024-07-05")]


def test_older_than_recorded_annual_crop_is_refused(env):
    env["orion"].crops, env["orion"].ops = [WHEAT], _wheat_ops()
    r = post({"eppo": "OLVEU", "planting_year": 2000})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "overlaps_recorded_crop"
    assert env["orion"].created == []


def test_after_recorded_annual_crop_is_allowed(env):
    env["orion"].crops, env["orion"].ops = [WHEAT], _wheat_ops()
    assert post({"eppo": "OLVEU", "planting_year": 2025}).status_code == 201


def test_any_open_main_crop_blocks_even_with_a_later_cover_crop(env):
    cover = {"id": "urn:ngsi-ld:AgriCrop:acme:p1:cover", "type": "AgriCrop", "hasAgriParcel": P,
             "status": "active", "cropRole": "cover_crop", "species": "VICSA", "plantingDate": "2026-10-01",
             "plantingDateSource": "manual"}
    olive = {"id": "urn:ngsi-ld:AgriCrop:acme:p1:olive", "type": "AgriCrop", "hasAgriParcel": P, "status": "active",
             "cropRole": "main_crop", "species": "OLVEU", "cropLifecycle": "perennial",
             "plantingDate": "1995-01-01", "plantingDateSource": "manual"}
    env["orion"].crops = [olive, cover]
    r = post({"eppo": "OLVEU", "planting_year": 2000})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "parcel_has_current_crop"
    assert r.json()["detail"]["crop_id"] == olive["id"]


def test_variety_over_100_chars_is_422(env):
    r = post({"eppo": "OLVEU", "planting_year": 2000, "variety": "x" * 101})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_variety"
    assert post({"eppo": "OLVEU", "planting_year": 2000, "variety": "x" * 100}).status_code == 201


def test_tenant_comes_from_the_gateway_header_not_the_body(env):
    r = TestClient(app).post(URL, headers={**H, "X-Tenant-ID": "acme"},
                             json={"eppo": "OLVEU", "planting_year": 2000, "tenant_id": "other", "tenant": "other"})
    assert r.status_code == 201 and r.json() == {"crop_id": OWN}
    assert env["reconciled"] == [("acme", P)]
    assert "other" not in env["orion"].created[0]["id"]
