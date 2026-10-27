"""Manual irrigation completed on a day that a water meter already recorded."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.api import operations as ops_route
from app.main import app
from app.services.irrigation_bridge import operation_id as sensor_op_id

client = TestClient(app)
BASE = "/api/field-operations"
TENANT = "tenant-a"
PARCEL = "urn:ngsi-ld:AgriParcel:p-1"
OP_ID = "urn:ngsi-ld:AgriParcelOperation:manual-1"
TODAY = dt.date(2026, 10, 25)
SENSOR_ID = sensor_op_id(TENANT, PARCEL, TODAY)
FARMER = {"X-Tenant-ID": TENANT, "X-User-ID": "u-farmer", "X-User-Roles": "Farmer"}
MANAGER = {"X-Tenant-ID": TENANT, "X-User-ID": "u-mgr", "X-User-Roles": "TechnicalConsultant"}


def _prop(value):
    return {"type": "Property", "value": value}


def _manual(op_type="irrigation", source="manual"):
    return {
        "id": OP_ID, "type": "AgriParcelOperation",
        "status": _prop("incomplete"), "operationType": _prop(op_type),
        "dataSource": _prop(source),
        "hasAgriParcel": {"type": "Relationship", "object": PARCEL},
        "waterPerHectare": _prop(100),
    }


def _sensor(status="completed", log=None):
    return {
        "id": SENSOR_ID, "type": "AgriParcelOperation",
        "status": _prop(status), "operationType": _prop("irrigation"),
        "dataSource": _prop("sensor"), "waterPerHectare": _prop(1500),
        "modificationLog": _prop(log if log is not None else []),
    }


@pytest.fixture
def env(monkeypatch):
    state = {"entities": {OP_ID: _manual()}, "completed": [], "updates": [], "lookups": []}

    def get_entity(tenant, eid):
        state["lookups"].append(eid)
        if eid == "urn:ngsi-ld:AgriParcel:p-1":
            return {"id": PARCEL, "type": "AgriParcel"}
        return state["entities"].get(eid)

    def complete(tenant, eid, **kw):
        state["completed"].append((eid, kw))
        return {}

    def update(tenant, eid, attrs):
        state["updates"].append((eid, attrs))
        return attrs

    monkeypatch.setattr(ops_route, "get_entity", get_entity)
    monkeypatch.setattr(ops_route, "complete_operation", complete)
    monkeypatch.setattr(ops_route, "update_entity_attrs", update)
    monkeypatch.setattr(ops_route, "_today", lambda p: TODAY)
    return state


def _complete(body, headers=FARMER):
    return client.post(f"{BASE}/operations/{OP_ID}/complete", headers=headers, json=body)


def test_409_when_a_sensor_operation_exists_and_no_choice(env):
    env["entities"][SENSOR_ID] = _sensor()
    r = _complete({})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "sensor_irrigation_exists"
    assert d["sensorOperationId"] == SENSOR_ID
    assert d["sensorWaterPerHectare"] == 1500
    assert d["day"] == "2026-10-25"
    assert env["completed"] == [] and env["updates"] == []


def test_completed_on_selects_the_day_to_check(env):
    day = dt.date(2026, 10, 20)
    sid = sensor_op_id(TENANT, PARCEL, day)
    env["entities"][sid] = {**_sensor(), "id": sid}
    r = _complete({"completedOn": "2026-10-20"})
    assert r.status_code == 409
    assert r.json()["detail"]["sensorOperationId"] == sid
    assert r.json()["detail"]["day"] == "2026-10-20"
    # the completion body for another day is not affected by today's meter op
    env["entities"][SENSOR_ID] = _sensor()
    assert _complete({"completedOn": "2026-10-19"}).status_code == 200


def test_keep_both_completes_and_links_the_sensor_operation(env):
    env["entities"][SENSOR_ID] = _sensor()
    r = _complete({"sensorOverlap": "keep_both"})
    assert r.status_code == 200, r.text
    (eid, kw), = env["completed"]
    assert eid == OP_ID
    assert "sensorOverlap" not in kw["extra_attrs"]
    raw = kw["raw_attrs"]
    assert raw["possibleDuplicateOf"] == {"type": "Relationship", "object": SENSOR_ID}
    assert raw["duplicateReview"] == {
        "type": "Property", "value": {"decision": "keep_both", "reviewed": [SENSOR_ID]}}
    # the meter operation records the review too, without a modificationLog entry
    (sid, attrs), = env["updates"]
    assert sid == SENSOR_ID
    assert attrs == {"duplicateReview": {
        "type": "Property", "value": {"decision": "keep_both", "reviewed": [OP_ID]}}}


def test_keep_both_keeps_earlier_reviewed_ids_on_the_meter_operation(env):
    meter = _sensor()
    meter["duplicateReview"] = _prop({"decision": "keep_both", "reviewed": ["urn:x:earlier"]})
    env["entities"][SENSOR_ID] = meter
    assert _complete({"sensorOverlap": "keep_both"}).status_code == 200
    (_, attrs), = env["updates"]
    assert attrs["duplicateReview"]["value"]["reviewed"] == sorted(["urn:x:earlier", OP_ID])


def test_ended_at_is_the_checked_day_when_no_completed_on(env):
    assert _complete({}).status_code == 200
    assert env["completed"][0][1]["ended_at"] == "2026-10-25T12:00:00Z"


def test_non_irrigation_keeps_now_when_no_completed_on(env):
    env["entities"][OP_ID] = _manual(op_type="tillage")
    env["entities"][OP_ID]["tillageType"] = _prop("plough")
    assert _complete({}).status_code == 200
    assert env["completed"][0][1].get("ended_at") is None


def test_replace_sensor_by_manager_cancels_sensor_then_completes(env):
    prev = {"field": "waterVolume", "by": "sensor"}
    env["entities"][SENSOR_ID] = _sensor(log=[prev])
    r = _complete({"sensorOverlap": "replace_sensor"}, MANAGER)
    assert r.status_code == 200, r.text
    (sid, attrs), = env["updates"]
    assert sid == SENSOR_ID
    assert attrs["status"]["value"] == "cancelled"
    assert attrs["cancellationReason"]["value"] == "replaced by a manual record"
    log = attrs["modificationLog"]["value"]
    assert log[0] == prev and log[-1]["by"] == "u-mgr" and log[-1]["method"] == "manual_cancellation"
    (eid, kw), = env["completed"]
    assert eid == OP_ID
    assert not kw.get("raw_attrs")
    assert "sensorOverlap" not in kw["extra_attrs"]


def test_replace_sensor_by_farmer_is_403_and_writes_nothing(env):
    env["entities"][SENSOR_ID] = _sensor()
    r = _complete({"sensorOverlap": "replace_sensor"}, FARMER)
    assert r.status_code == 403
    assert env["updates"] == [] and env["completed"] == []


def test_invalid_overlap_value_is_422(env):
    env["entities"][SENSOR_ID] = _sensor()
    r = _complete({"sensorOverlap": "merge"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_sensor_overlap"
    assert env["completed"] == [] and env["updates"] == []


def test_no_sensor_operation_completes_as_before(env):
    r = _complete({})
    assert r.status_code == 200
    (_, kw), = env["completed"]
    assert not kw.get("raw_attrs")


def test_cancelled_sensor_operation_does_not_count(env):
    env["entities"][SENSOR_ID] = _sensor(status="cancelled")
    r = _complete({})
    assert r.status_code == 200
    assert not env["completed"][0][1].get("raw_attrs")


def test_overlap_without_a_sensor_operation_is_not_stored(env):
    r = _complete({"sensorOverlap": "keep_both"})
    assert r.status_code == 200
    (_, kw), = env["completed"]
    assert "sensorOverlap" not in kw["extra_attrs"]
    assert not kw.get("raw_attrs")


def test_non_irrigation_is_untouched(env):
    env["entities"][OP_ID] = _manual(op_type="tillage")
    env["entities"][OP_ID]["tillageType"] = _prop("plough")
    env["entities"][SENSOR_ID] = _sensor()
    r = _complete({})
    assert r.status_code == 200
    assert SENSOR_ID not in env["lookups"]


def test_sensor_source_operation_is_not_checked(env):
    env["entities"][OP_ID] = _manual(source="sensor")
    env["entities"][SENSOR_ID] = _sensor()
    assert _complete({}).status_code == 200
    assert SENSOR_ID not in env["lookups"]


# --- duplicate-review ------------------------------------------------------------------------

def _flagged(**extra):
    e = _sensor()
    e["possibleDuplicateOf"] = {"type": "Relationship", "object": [OP_ID]}
    e.update(extra)
    return e


def _review(body, headers=FARMER):
    return client.post(f"{BASE}/operations/{SENSOR_ID}/duplicate-review", headers=headers, json=body)


def test_review_keep_both_writes_only_duplicate_review(env):
    env["entities"][SENSOR_ID] = _flagged()
    r = _review({"decision": "keep_both"})
    assert r.status_code == 200, r.text
    (eid, attrs), = env["updates"]
    assert eid == SENSOR_ID
    assert attrs == {"duplicateReview": {
        "type": "Property", "value": {"decision": "keep_both", "reviewed": [OP_ID]}}}


def test_review_records_every_flagged_id(env):
    env["entities"][SENSOR_ID] = _flagged(
        possibleDuplicateOf={"type": "Relationship", "object": ["urn:x:b", OP_ID]})
    assert _review({"decision": "keep_both"}).status_code == 200
    (_, attrs), = env["updates"]
    assert attrs["duplicateReview"]["value"]["reviewed"] == sorted(["urn:x:b", OP_ID])


def test_review_other_decision_is_422(env):
    env["entities"][SENSOR_ID] = _flagged()
    r = _review({"decision": "delete"})
    assert r.status_code == 422
    assert env["updates"] == []


def test_review_of_a_non_sensor_or_open_operation_is_403(env):
    manual = _flagged()
    manual["dataSource"] = _prop("manual")
    env["entities"][SENSOR_ID] = manual
    assert _review({"decision": "keep_both"}).status_code == 403
    env["entities"][SENSOR_ID] = _flagged(status=_prop("cancelled"))
    assert _review({"decision": "keep_both"}).status_code == 403
    assert env["updates"] == []


def test_review_of_an_unflagged_sensor_operation_is_400(env):
    env["entities"][SENSOR_ID] = _sensor()
    assert _review({"decision": "keep_both"}).status_code == 400
    assert env["updates"] == []


def test_review_of_a_missing_operation_is_404(env):
    assert _review({"decision": "keep_both"}).status_code == 404
