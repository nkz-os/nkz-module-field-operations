"""POST /operations/record and GET /parcels: record a past sowing or harvest from the UI."""
import httpx
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
        self.stored, self.gets = {}, []

    async def get_entity(self, eid, options=None):
        self.gets.append(eid)
        if eid in self.stored:
            return self.stored[eid]
        if eid.startswith("urn:ngsi-ld:AgriParcelOperation:"):
            req = httpx.Request("GET", "http://orion/x")
            raise httpx.HTTPStatusError("nf", request=req, response=httpx.Response(404, request=req))
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
    ({**_sow(), "operation_type": "bogus"}, "unsupported_type"),
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


OLIVE = {"id": "urn:ngsi-ld:AgriCrop:acme:p1:olive", "type": "AgriCrop", "refAgriParcel": P, "status": "active",
         "cropRole": "main_crop", "species": "OLVEU", "cropLifecycle": "perennial",
         "plantingDate": "2010-03-01", "plantingDateSource": "manual"}


def test_record_perennial_harvest_201(env):
    env["orion"] = FakeOrion([OLIVE])
    r = TestClient(app).post(URL, headers=H, json={"parcel_id": P, "operation_type": "harvesting",
                                                   "date": "2026-11-10", "harvestedWeight": 900})
    assert r.status_code == 201, r.text
    assert r.json()["crop_id"] == OLIVE["id"] and r.json()["harvest_campaign"] == "2026/27"
    assert r.json()["harvest_campaign_label"] == 2026 and r.json()["campaign"] is None
    assert env["created"][0][1]["operation_type"] == "harvesting"


def test_record_uprooting_stored_as_tillage(env):
    env["orion"] = FakeOrion([OLIVE])
    r = TestClient(app).post(URL, headers=H, json={"parcel_id": P, "operation_type": "uprooting",
                                                   "date": "2026-11-10"})
    assert r.status_code == 201, r.text
    kw = env["created"][0][1]
    assert kw["operation_type"] == "tillage" and kw["tillageType"] == "uprooting"
    assert kw["crop_id"] == OLIVE["id"]


def test_uprooting_with_closed_and_open_stand_links_the_open_one(env):
    old = dict(OLIVE, id="urn:ngsi-ld:AgriCrop:acme:p1:old", plantingDate="1990-03-01", species="VITVI")
    done = {"id": "urn:ngsi-ld:AgriParcelOperation:acme:u0", "hasAgriParcel": P, "operationType": "tillage",
            "tillageType": "uprooting", "status": "completed", "endedAt": "2020-01-10", "hasAgriCrop": old["id"]}
    env["orion"] = FakeOrion([old, OLIVE], [done])
    r = _post({"parcel_id": P, "operation_type": "uprooting", "date": "2026-11-10"})
    assert r.status_code == 201, r.text
    assert env["created"][0][1]["crop_id"] == OLIVE["id"]


def test_create_operation_writes_has_agri_crop_relationship(monkeypatch):
    from app import orion_ops
    sent = []

    class C:
        context_url = "ctx"

        def create_entity(self, e):
            sent.append(e)

    monkeypatch.setattr(orion_ops, "_get_client", lambda t: C())
    orion_ops.create_operation("acme", parcel_id=P, operation_type="tillage", work_order="w", operator="u",
                               crop_id="urn:ngsi-ld:AgriCrop:acme:p1:olive", tillageType="uprooting")
    assert sent[0]["hasAgriCrop"] == {"type": "Relationship", "object": "urn:ngsi-ld:AgriCrop:acme:p1:olive"}


def test_record_uprooting_on_annual_409(env):
    r = TestClient(app).post(URL, headers=H, json={"parcel_id": P, "operation_type": "uprooting",
                                                   "date": "2026-11-10"})
    assert r.status_code == 409 and env["created"] == []


def _post(body):
    return TestClient(app).post(URL, headers=H, json=body)


def test_perennial_same_day_duplicate_409(env):
    op = {"id": "urn:ngsi-ld:AgriParcelOperation:acme:h1", "hasAgriParcel": P, "operationType": "harvesting",
          "status": "completed", "endedAt": "2026-11-10"}
    env["orion"] = FakeOrion([OLIVE], [op])
    r = _post({"parcel_id": P, "operation_type": "harvesting", "date": "2026-11-10", "harvestedWeight": 900})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_recorded"
    assert env["created"] == []


def test_uprooting_before_last_harvest_409(env):
    op = {"id": "urn:ngsi-ld:AgriParcelOperation:acme:h1", "hasAgriParcel": P, "operationType": "harvesting",
          "status": "completed", "endedAt": "2026-11-10"}
    env["orion"] = FakeOrion([OLIVE], [op])
    r = _post({"parcel_id": P, "operation_type": "uprooting", "date": "2026-11-01"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "date_before_last_harvest"
    assert env["created"] == []


def test_list_parcels_offers_uproot(env):
    env["orion"] = FakeOrion([OLIVE])
    r = TestClient(app).get("/api/field-operations/parcels", headers=H)
    [c] = r.json()["parcels"][0]["cycles"]
    assert c["can_uproot"] is True and c["can_harvest"] is True and c["can_sow"] is False
    assert c["harvest_campaigns"] == []


def test_parcel_list_broker_failure_is_a_503(env):
    class Down(FakeOrion):
        async def query_entities(self, **kw):
            raise __import__("httpx").ConnectError("down")
    env["orion"] = Down()
    r = TestClient(app).get("/api/field-operations/parcels", headers=H)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "crop_data_unavailable"


CID = "3f2b8c1e-5d4a-4e7b-9a1c-0d2e4f6a8b1c"
DET = f"urn:ngsi-ld:AgriParcelOperation:tenant-a:{CID}"


def _stored(**kw):
    e = {"id": DET, "type": "AgriParcelOperation",
         "hasAgriParcel": {"type": "Relationship", "object": P},
         "operationType": {"type": "Property", "value": "sowing"},
         "startedAt": {"type": "Property", "value": {"@type": "DateTime", "@value": "2026-11-10T12:00:00Z"}}}
    e.update(kw)
    return e


@pytest.mark.parametrize("cid", ["nope", "3f2b8c1e-5d4a-1e7b-9a1c-0d2e4f6a8b1c", 5, ""])
def test_bad_client_id_is_422(env, cid):
    r = TestClient(app).post(URL, headers=H, json=_sow(client_id=cid))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_client_id"
    assert env["created"] == []


def test_client_id_makes_a_deterministic_entity_id_lowercased(env):
    r = TestClient(app).post(URL, headers=H, json=_sow(client_id=CID.upper()))
    assert r.status_code == 201, r.text
    assert env["created"][0][1]["entity_id"] == DET
    body = r.json()
    assert body["operation_id"] == "urn:ngsi-ld:AgriParcelOperation:tenant-a:abc"
    assert body["duplicate"] is False and body["operation_type"] == "sowing"
    assert body["parcel_id"] == P and body["date"] == "2026-11-10"


def test_without_client_id_no_entity_id_and_no_lookup(env):
    r = TestClient(app).post(URL, headers=H, json=_sow())
    assert r.status_code == 201
    assert "entity_id" not in env["created"][0][1]
    assert not any(g.startswith("urn:ngsi-ld:AgriParcelOperation:") for g in env["orion"].gets)


def test_retry_returns_the_stored_record_without_matcher_or_create(env, monkeypatch):
    env["orion"].stored[DET] = _stored(hasAgriCrop={"type": "Relationship", "object": PLANNED["id"]})

    def boom(*a, **k):
        raise AssertionError("matcher must not run")
    monkeypatch.setattr(route, "match_record", boom)
    r = TestClient(app).post(URL, headers=H, json=_sow(client_id=CID))
    assert r.status_code == 200, r.text
    assert r.json() == {"operation_id": DET, "operation_type": "sowing", "parcel_id": P, "date": "2026-11-10",
                        "duplicate": True, "crop_id": PLANNED["id"], "species": None, "role": None,
                        "campaign": None, "harvest_campaign": None, "harvest_campaign_label": None,
                        "reconciled": False}
    assert env["created"] == [] and env["reconciled"] == []


def test_retry_maps_stored_uprooting_back_and_omits_missing_crop(env):
    env["orion"].stored[DET] = _stored(operationType={"type": "Property", "value": "tillage"},
                                       tillageType={"type": "Property", "value": "uprooting"})
    r = TestClient(app).post(URL, headers=H, json=_sow(client_id=CID))
    assert r.status_code == 200
    assert r.json()["operation_type"] == "uprooting" and r.json()["crop_id"] is None


def test_retry_with_a_different_body_returns_the_existing_record(env, caplog):
    env["orion"].stored[DET] = _stored()
    with caplog.at_level("WARNING"):
        r = TestClient(app).post(URL, headers=H, json=_sow(client_id=CID, seedingRate=999, date="2026-11-11"))
    assert r.status_code == 200 and r.json()["date"] == "2026-11-10" and r.json()["duplicate"] is True
    assert any("client_id" in m and "differ" in m for m in caplog.messages)
    assert "999" not in caplog.text


def test_create_hitting_an_existing_entity_rereads_and_answers_duplicate(env, monkeypatch):
    orion = env["orion"]

    def clash(tenant_id, **kw):
        orion.stored[DET] = _stored()  # the concurrent request landed first
        raise route.EntityAlreadyExists("exists")
    monkeypatch.setattr(route, "create_operation", clash)
    r = TestClient(app).post(URL, headers=H, json=_sow(client_id=CID))
    assert r.status_code == 200 and r.json()["duplicate"] is True and r.json()["operation_id"] == DET


def test_lookup_failure_other_than_404_is_503(env):
    async def broken(eid, options=None):
        raise httpx.ConnectError("down")
    env["orion"].get_entity = broken
    r = TestClient(app).post(URL, headers=H, json=_sow(client_id=CID))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "store_unavailable"
    assert env["created"] == []


def test_notes_over_500_chars_is_422(env):
    r = TestClient(app).post(URL, headers=H, json=_sow(notes="x" * 501))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_notes"
    assert env["created"] == []
    assert TestClient(app).post(URL, headers=H, json=_sow(notes="x" * 500)).status_code == 201


# ---- the types recorded as completed facts (no crop window) ----
class _CropFail(FakeOrion):
    async def query_entities(self, type=None, **kw):
        if type in ("AgriCrop", "AgriParcelOperation"):
            raise httpx.ConnectError("down")
        return await super().query_entities(type=type, **kw)


ACTIVE = {"id": "urn:ngsi-ld:AgriCrop:t:p1:a", "type": "AgriCrop", "refAgriParcel": P, "status": "active",
          "cropRole": "main_crop", "species": "TRZAX", "plantingDate": "2026-10-01",
          "plantingDateSource": "manual", "expectedTerminationDate": "2027-07-31"}


def _fact(op, **kw):
    return {"parcel_id": P, "operation_type": op, "date": "2026-11-10", **kw}


def test_irrigation_recorded_without_crop_window(env):
    env["orion"] = FakeOrion([])
    r = TestClient(app).post(URL, headers=H, json=_fact("irrigation", waterPerHectare=15000))
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["operation_type"] == "irrigation" and b["duplicate"] is False and b["crop_id"] is None
    assert b["reconciled"] is False
    _, kw = env["created"][0]
    assert kw["waterPerHectare"] == 15000.0 and kw["status"] == "completed" and "crop_id" not in kw
    assert kw["work_order"] == "REG-2026-11-10" and kw["startedAt"] == "2026-11-10T12:00:00Z"


def test_single_current_crop_sets_the_relationship(env):
    env["orion"] = FakeOrion([ACTIVE])
    r = TestClient(app).post(URL, headers=H, json=_fact("irrigation", waterPerHectare=100))
    assert r.status_code == 201 and r.json()["crop_id"] == ACTIVE["id"]
    assert env["created"][0][1]["crop_id"] == ACTIVE["id"]


def test_ambiguous_crops_record_without_relationship(env):
    other = dict(ACTIVE, id="urn:ngsi-ld:AgriCrop:t:p1:b")
    env["orion"] = FakeOrion([ACTIVE, other])
    r = TestClient(app).post(URL, headers=H, json=_fact("irrigation", waterPerHectare=100))
    assert r.status_code == 201 and r.json()["crop_id"] is None


def test_unreadable_crops_still_record(env):
    env["orion"] = _CropFail([])
    r = TestClient(app).post(URL, headers=H, json=_fact("irrigation", waterPerHectare=100))
    assert r.status_code == 201 and r.json()["crop_id"] is None
    assert "crop_id" not in env["created"][0][1]


def test_unknown_parcel_is_404(env):
    class NoParcel(FakeOrion):
        async def get_entity(self, eid, options=None):
            req = httpx.Request("GET", "http://orion/x")
            raise httpx.HTTPStatusError("nf", request=req, response=httpx.Response(404, request=req))
    env["orion"] = NoParcel([])
    r = TestClient(app).post(URL, headers=H, json=_fact("irrigation", waterPerHectare=1))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "parcel_not_found"
    assert env["created"] == []


@pytest.mark.parametrize("day,status", [("2026-11-21", 201), ("2026-11-22", 409)])
def test_future_date_has_one_day_margin(env, day, status):
    env["orion"] = FakeOrion([])
    r = TestClient(app).post(URL, headers=H, json=_fact("irrigation", waterPerHectare=1, date=day))
    assert r.status_code == status
    if status == 409:
        assert r.json()["detail"]["code"] == "future_date" and env["created"] == []


def test_fertilization_stored_in_kg_per_ha(env):
    env["orion"] = FakeOrion([])
    r = TestClient(app).post(URL, headers=H, json=_fact(
        "fertilization", fertilizerType="N32", rate=200, rateUnit="L/ha", density=1.32,
        composition={"n": 32, "p": 0, "k": 0}))
    assert r.status_code == 201, r.text
    kw = env["created"][0][1]
    assert kw["fertilizerRate"] == 264.0 and kw["fertilizerRateInput"] == 200.0
    assert kw["nitrogenContent"] == {"value": 32.0, "unitCode": "P1"} and kw["fertilizerComposition"] == "32-0-0"


def test_spraying_reports_not_checked(env):
    env["orion"] = FakeOrion([])
    r = TestClient(app).post(URL, headers=H, json=_fact("spraying", productName="X", productRate=2))
    assert r.status_code == 201 and r.json()["authorization"] == "not_checked"
    assert env["created"][0][1]["productRateUnit"] == "L/ha"


def test_tillage_rejects_uprooting_and_reconciles(env):
    env["orion"] = FakeOrion([])
    r = TestClient(app).post(URL, headers=H, json=_fact("tillage", tillageType="uprooting"))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_tillage_type"
    r = TestClient(app).post(URL, headers=H, json=_fact("tillage", tillageType="mowing", depth=5))
    assert r.status_code == 201 and r.json()["reconciled"] is True
    assert env["created"][0][1]["tillageDepth"] == 5.0


def test_haymaking_takes_crop_type_from_the_current_crop(env):
    env["orion"] = FakeOrion([ACTIVE])
    r = TestClient(app).post(URL, headers=H, json=_fact("haymaking", swathType="raking"))
    assert r.status_code == 201, r.text
    assert env["created"][0][1]["cropType"] == "TRZAX"


@pytest.mark.parametrize("op,extra", [("haymaking", {"swathType": "raking"}),
                                      ("baling", {"baleType": "round", "baleCount": 4})])
def test_haymaking_and_baling_need_a_crop(env, op, extra):
    env["orion"] = FakeOrion([])
    r = TestClient(app).post(URL, headers=H, json=_fact(op, **extra))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_crop_on_date"
    assert env["created"] == []


def test_baling_with_unreadable_crops_is_503(env):
    env["orion"] = _CropFail([])
    r = TestClient(app).post(URL, headers=H, json=_fact("baling", baleType="round", baleCount=4))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "crop_data_unavailable"


def test_scouting_needs_notes(env):
    env["orion"] = FakeOrion([])
    r = TestClient(app).post(URL, headers=H, json=_fact("scouting"))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "missing_fields"
    r = TestClient(app).post(URL, headers=H, json=_fact("scouting", notes="aphids"))
    assert r.status_code == 201 and env["created"][0][1]["platformType"] == "manual"


FCID = "11111111-1111-4111-8111-111111111111"


def test_fact_with_client_id_is_idempotent(env):
    env["orion"] = FakeOrion([])
    eid = f"urn:ngsi-ld:AgriParcelOperation:tenant-a:{FCID}"
    r = TestClient(app).post(URL, headers=H, json=_fact("irrigation", waterPerHectare=1, client_id=FCID))
    assert r.status_code == 201 and env["created"][0][1]["entity_id"] == eid
    env["orion"].stored[eid] = {"id": eid, "operationType": {"value": "irrigation"},
                                "hasAgriParcel": {"object": P}, "startedAt": {"value": "2026-11-10T12:00:00Z"}}
    r = TestClient(app).post(URL, headers=H, json=_fact("irrigation", waterPerHectare=1, client_id=FCID))
    assert r.status_code == 200 and r.json()["duplicate"] is True and len(env["created"]) == 1


def test_huge_rate_is_a_422_not_a_500(env):
    env["orion"] = FakeOrion([])
    r = TestClient(app).post(URL, headers=H, json=_fact("fertilization", fertilizerType="x", rate=1e308, rateUnit="t/ha"))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_number"


def test_planned_only_cycle_binds_fertilization_but_not_hay(env):
    env["orion"] = FakeOrion([PLANNED])
    day = "2026-11-15"
    r = TestClient(app).post(URL, headers=H, json=_fact("fertilization", fertilizerType="x", rate=1, date=day))
    assert r.status_code == 201 and r.json()["crop_id"] == PLANNED["id"]
    r = TestClient(app).post(URL, headers=H, json=_fact("haymaking", swathType="raking", date=day))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_crop_on_date"


def test_non_terminating_tillage_does_not_reconcile(env):
    env["orion"] = FakeOrion([])
    r = TestClient(app).post(URL, headers=H, json=_fact("tillage", tillageType="ploughing"))
    assert r.status_code == 201 and r.json()["reconciled"] is False and env["reconciled"] == []
