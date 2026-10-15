"""POST /operations/record and GET /parcels: record a past sowing or harvest from the UI."""
import pytest
from fastapi.testclient import TestClient

from app.api import record as route
from app.main import app

P = "urn:ngsi-ld:AgriParcel:p1"
H = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u1"}
URL = "/api/field-operations/operations/record"
PLANNED = {"id": "urn:ngsi-ld:AgriCrop:t:p1:2027:1", "type": "AgriCrop", "refAgriParcel": P,
           "status": "planned", "cropRole": "main_crop", "species": "TRZAX", "variety": "KWS KEITUM",
           "sowingWindowStart": "2026-11-01", "expectedTerminationDate": "2027-07-31"}


class FakeOrion:
    def __init__(self, crops=(), ops=(), parcels=None):
        self.parcel = {"id": P, "type": "AgriParcel", "name": "Soto Alto", "area": 12.5}
        self.crops, self.ops = list(crops), list(ops)
        self.parcels = parcels if parcels is not None else [self.parcel]

    async def get_entity(self, eid, options=None):
        return self.parcel

    async def query_entities(self, type=None, q=None, limit=100, offset=0, attrs=None, options=None):
        if type == "AgriParcel":
            return self.parcels[offset:offset + limit]
        return self.crops if type == "AgriCrop" else self.ops

    async def close(self):
        pass


@pytest.fixture
def env(monkeypatch):
    state = {"orion": FakeOrion([PLANNED]), "created": [], "reconciled": []}
    monkeypatch.setattr(route, "_orion", lambda tenant: state["orion"])
    monkeypatch.setattr(route, "_today", lambda parcel: __import__("datetime").date(2026, 11, 20))

    def fake_create(tenant_id, **kw):
        state["created"].append((tenant_id, kw))
        return {"id": "urn:ngsi-ld:AgriParcelOperation:tenant-a:abc"}

    async def fake_reconcile(client, tenant_id, parcel):
        state["reconciled"].append((tenant_id, parcel))
        return []

    monkeypatch.setattr(route, "create_operation", fake_create)
    monkeypatch.setattr(route, "reconcile_parcel", fake_reconcile)
    monkeypatch.setattr(route.config, "CROP_CYCLES_WRITER_ENABLED", True)
    return state


def _sow(**kw):
    return {"parcel_id": P, "operation_type": "sowing", "date": "2026-11-10", "seedingRate": 180, **kw}


def test_sowing_is_stored_completed_with_its_real_date_and_reconciled(env):
    r = TestClient(app).post(URL, headers=H, json=_sow(sowingMethod="direct"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["crop_id"] == PLANNED["id"] and body["species"] == "TRZAX" and body["campaign"] == 2027
    tenant, kw = env["created"][0]
    assert tenant == "tenant-a" and kw["status"] == "completed" and kw["operation_type"] == "sowing"
    assert kw["parcel_id"] == P and kw["data_source"] == "manual" and kw["operator"] == "u1"
    assert kw["startedAt"].startswith("2026-11-10") and kw["endedAt"].startswith("2026-11-10")
    assert kw["cropType"] == "TRZAX" and kw["variety"] == "KWS KEITUM" and kw["seedingRate"] == 180
    assert kw["sowingMethod"] == "direct"
    assert env["reconciled"] == [("tenant-a", P)]


def test_variety_typed_by_the_user_wins_over_the_plan(env):
    TestClient(app).post(URL, headers=H, json=_sow(variety="Califa"))
    assert env["created"][0][1]["variety"] == "Califa"


def test_unmatched_sowing_is_refused_and_nothing_written(env):
    env["orion"] = FakeOrion([])
    r = TestClient(app).post(URL, headers=H, json=_sow())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_planned_crop"
    assert env["created"] == [] and env["reconciled"] == []


@pytest.mark.parametrize("body,code", [
    ({"parcel_id": P, "operation_type": "sowing", "date": "2026-11-10"}, "missing_fields"),
    ({**_sow(), "date": "10/11/2026"}, "invalid_date"),
    ({**_sow(), "operation_type": "spraying"}, "unsupported_type"),
    ({**_sow(), "sowingMethod": "magic"}, "invalid_sowing_method"),
    ({"parcel_id": P, "operation_type": "harvesting", "date": "2026-11-10"}, "missing_fields"),
])
def test_bad_input_is_a_422_with_a_code(env, body, code):
    r = TestClient(app).post(URL, headers=H, json=body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == code
    assert env["created"] == []


def test_bare_parcel_id_is_normalised(env):
    TestClient(app).post(URL, headers=H, json=_sow(parcel_id="p1"))
    assert env["created"][0][1]["parcel_id"] == P


def test_reconcile_failure_does_not_undo_the_record(env, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("broker slow")
    monkeypatch.setattr(route, "reconcile_parcel", boom)
    r = TestClient(app).post(URL, headers=H, json=_sow())
    assert r.status_code == 201 and r.json()["reconciled"] is False


def test_parcels_list_what_can_be_sown_and_harvested(env):
    env["orion"] = FakeOrion([PLANNED])
    r = TestClient(app).get("/api/field-operations/parcels", headers=H)
    assert r.status_code == 200, r.text
    [p] = r.json()["parcels"]
    assert p["id"] == P and p["name"] == "Soto Alto"
    [c] = p["cycles"]
    assert c["crop_id"] == PLANNED["id"] and c["species"] == "TRZAX" and c["variety"] == "KWS KEITUM"
    assert c["can_sow"] is True and c["can_harvest"] is False
    assert c["start"]["provenance"] == "planned"


def test_routes_need_identity(env):
    assert TestClient(app).post(URL, json=_sow()).status_code == 401
    assert TestClient(app).get("/api/field-operations/parcels").status_code == 401


def test_sowing_without_variety_in_plan_or_form_is_refused(env):
    no_variety = {k: v for k, v in PLANNED.items() if k != "variety"}
    env["orion"] = FakeOrion([no_variety])
    r = TestClient(app).post(URL, headers=H, json=_sow())
    assert r.status_code == 422 and r.json()["detail"]["code"] == "missing_fields"
    assert env["created"] == []


def test_date_landing_on_another_crop_than_the_chosen_one_is_refused(env):
    r = TestClient(app).post(URL, headers=H, json=_sow(crop_id="urn:ngsi-ld:AgriCrop:t:p1:2027:0"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "date_outside_crop_window"
    assert r.json()["detail"]["landed_on"] == PLANNED["id"]
    assert env["created"] == []


def test_chosen_crop_matching_the_date_is_recorded(env):
    r = TestClient(app).post(URL, headers=H, json=_sow(crop_id=PLANNED["id"]))
    assert r.status_code == 201


@pytest.mark.parametrize("exc", [RuntimeError("Orion-LD create failed (503)"),
                                 __import__("requests").ConnectionError("down")])
def test_broker_failure_on_write_is_a_503_with_a_code(env, monkeypatch, exc):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(route, "create_operation", boom)
    r = TestClient(app).post(URL, headers=H, json=_sow())
    assert r.status_code == 503 and r.json()["detail"]["code"] == "store_unavailable"
    assert env["reconciled"] == []


@pytest.mark.parametrize("pid", ['p1" || true', "../x", "x" * 300])
def test_malformed_parcel_id_is_refused(env, pid):
    r = TestClient(app).post(URL, headers=H, json=_sow(parcel_id=pid))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_parcel"


@pytest.mark.parametrize("field,value", [("seedingRate", "abc"), ("seedingRate", -5), ("seedingRate", 0)])
def test_numbers_must_be_positive(env, field, value):
    r = TestClient(app).post(URL, headers=H, json=_sow(**{field: value}))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_number"
    assert env["created"] == []


def test_harvest_weight_must_be_positive(env):
    r = TestClient(app).post(URL, headers=H, json={"parcel_id": P, "operation_type": "harvesting",
                                                   "date": "2026-11-10", "harvestedWeight": "-1"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_number"


def test_parcels_carry_the_crop_name_and_survive_odd_names(env):
    named = dict(PLANNED, name="trigo")
    env["orion"] = FakeOrion([named], parcels=[{"id": P, "name": {"es": "Soto"}}])
    r = TestClient(app).get("/api/field-operations/parcels", headers=H)
    assert r.status_code == 200
    assert r.json()["parcels"][0]["cycles"][0]["name"] == "trigo"


def test_perennial_is_not_offered_for_harvest(env):
    vine = {"id": "urn:ngsi-ld:AgriCrop:t:p1:vine", "type": "AgriCrop", "refAgriParcel": P, "status": "active",
            "cropRole": "main_crop", "species": "VITVI", "cropLifecycle": "perennial",
            "plantingDate": "2010-03-01", "plantingDateSource": "manual"}
    env["orion"] = FakeOrion([vine])
    r = TestClient(app).get("/api/field-operations/parcels", headers=H)
    assert r.json()["parcels"][0]["cycles"] == []


def test_parcel_list_broker_failure_is_a_503(env):
    class Down(FakeOrion):
        async def query_entities(self, **kw):
            raise __import__("httpx").ConnectError("down")
    env["orion"] = Down()
    r = TestClient(app).get("/api/field-operations/parcels", headers=H)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "crop_data_unavailable"
