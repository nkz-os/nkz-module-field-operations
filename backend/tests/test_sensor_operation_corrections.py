"""Cancel or correct completed irrigation operations that the water-meter bridge created."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.state_machine import can_transition

client = TestClient(app)
H = {"X-User-ID": "u1", "X-Tenant-ID": "tenant-a", "X-User-Roles": "field_manager"}
FARMER = {"X-User-ID": "u2", "X-Tenant-ID": "tenant-a", "X-User-Roles": "Farmer"}
BASE = "/api/field-operations/operations/op1"


def _op(status="completed", source="sensor", op_type="irrigation", log=None):
    return {
        "status": {"value": status}, "dataSource": {"value": source},
        "operationType": {"value": op_type}, "waterPerHectare": {"value": 120},
        "modificationLog": {"value": log if log is not None else []},
    }


def _post(path, body, op, headers=H):
    with patch("app.api.operations._get_or_404", return_value=op), \
         patch("app.api.operations.update_entity_attrs", return_value={}) as upd:
        r = client.post(f"{BASE}/{path}", json=body, headers=headers)
    return r, upd


def test_state_machine_completed_cancel_only_for_sensor():
    assert can_transition("completed", "cancelled", "field_manager", data_source="sensor").allowed
    assert not can_transition("completed", "cancelled", "user", data_source="sensor").allowed
    assert not can_transition("completed", "cancelled", "user").allowed
    assert not can_transition("completed", "cancelled", "user", data_source="manual").allowed
    assert not can_transition("completed", "cancelled", "system", data_source="sensor").allowed


def test_cancel_completed_sensor_op_logs_user():
    r, upd = _post("cancel", {"cancellationReason": "meter fault"}, _op())
    assert r.status_code == 200
    attrs = upd.call_args.args[2]
    assert attrs["status"]["value"] == "cancelled"
    entry = attrs["modificationLog"]["value"][-1]
    assert entry["by"] == "u1" and entry["by"] != "sensor"
    assert entry["method"] == "manual_cancellation" and entry["reason"] == "meter fault"


def test_cancel_completed_manual_op_is_403():
    r, upd = _post("cancel", {"cancellationReason": "x"}, _op(source="manual"))
    assert r.status_code == 403
    upd.assert_not_called()


def test_cancel_keeps_previous_log_entries():
    prev = {"field": "waterVolume", "by": "sensor"}
    r, upd = _post("cancel", {"cancellationReason": "x"}, _op(log=[prev]))
    log = upd.call_args.args[2]["modificationLog"]["value"]
    assert log[0] == prev and len(log) == 2


def test_correct_updates_dose_and_logs_user():
    r, upd = _post("correct", {"waterPerHectare": 90, "reason": "wrong meter"}, _op())
    assert r.status_code == 200
    attrs = upd.call_args.args[2]
    assert attrs["waterPerHectare"]["value"] == 90
    assert "dataSource" not in attrs and "status" not in attrs
    entry = attrs["modificationLog"]["value"][-1]
    assert entry["by"] == "u1" and entry["field"] == "waterPerHectare"
    assert entry["old"] == 120 and entry["new"] == 90
    assert entry["method"] == "manual_correction" and entry["reason"] == "wrong meter"
    assert entry["at"]


def test_correct_non_sensor_is_403():
    r, upd = _post("correct", {"waterPerHectare": 90, "reason": "x"}, _op(source="manual"))
    assert r.status_code == 403
    upd.assert_not_called()


def test_correct_non_completed_or_non_irrigation_is_403():
    assert _post("correct", {"waterPerHectare": 9, "reason": "x"}, _op(status="cancelled"))[0].status_code == 403
    assert _post("correct", {"waterPerHectare": 9, "reason": "x"}, _op(op_type="spraying"))[0].status_code == 403


def test_correct_non_positive_dose_is_422():
    for bad in (0, -5, "abc", True, None):
        r, upd = _post("correct", {"waterPerHectare": bad, "reason": "x"}, _op())
        assert r.status_code == 422, bad
        upd.assert_not_called()


def test_correct_missing_reason_is_400():
    for body in ({"waterPerHectare": 90}, {"waterPerHectare": 90, "reason": "  "}):
        r, upd = _post("correct", body, _op())
        assert r.status_code == 400
        upd.assert_not_called()


def test_dict_valued_log_is_kept_on_correct_and_cancel():
    old = {"field": "waterVolume", "by": "sensor"}
    for path, body in (("correct", {"waterPerHectare": 90, "reason": "x"}),
                       ("cancel", {"cancellationReason": "x"})):
        op = _op()
        op["modificationLog"] = {"type": "Property", "value": old}
        r, upd = _post(path, body, op)
        assert r.status_code == 200
        log = upd.call_args.args[2]["modificationLog"]["value"]
        assert log[0] == old and len(log) == 2 and log[1]["by"] == "u1"


def test_correct_scales_volume_with_dose():
    op = _op()
    op["waterVolume"] = {"type": "Property", "value": 6.0, "unitCode": "MTQ"}
    r, upd = _post("correct", {"waterPerHectare": 60, "reason": "x"}, op)  # 120 -> 60
    attrs = upd.call_args.args[2]
    assert attrs["waterVolume"] == {"type": "Property", "value": 3.0, "unitCode": "MTQ"}
    entry = attrs["modificationLog"]["value"][-1]
    assert entry["fields"]["waterVolume"] == {"old": 6.0, "new": 3.0}
    assert entry["fields"]["waterPerHectare"] == {"old": 120, "new": 60}


def test_correct_without_volume_updates_dose_only():
    r, upd = _post("correct", {"waterPerHectare": 60, "reason": "x"}, _op())
    assert "waterVolume" not in upd.call_args.args[2]


def test_farmer_cannot_revoke_or_correct_sensor_operation():
    r, upd = _post("cancel", {"cancellationReason": "x"}, _op(), headers=FARMER)
    assert r.status_code == 403 and not upd.called
    r, upd = _post("correct", {"waterPerHectare": 90, "reason": "x"}, _op(), headers=FARMER)
    assert r.status_code == 403 and not upd.called
