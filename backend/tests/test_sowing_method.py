"""Optional sowing method on sowing operations (read by the crop simulation)."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
H = {"X-User-ID": "u1", "X-Tenant-ID": "test-tenant"}
BODY = {"parcel_id": "urn:ngsi-ld:AgriParcel:t:p1", "operation_type": "sowing", "work_order": "WO-1",
        "operator": "op@example.com"}


def test_create_with_direct_sowing_passes_it_through():
    with patch("app.api.operations.create_operation", return_value={"id": "x"}) as create:
        r = client.post("/api/field-operations/operations", json={**BODY, "sowingMethod": "direct"}, headers=H)
    assert r.status_code == 200
    assert create.call_args.kwargs["sowingMethod"] == "direct"


def test_create_with_unknown_method_is_400():
    with patch("app.api.operations.create_operation") as create:
        r = client.post("/api/field-operations/operations", json={**BODY, "sowingMethod": "no-till"}, headers=H)
    assert r.status_code == 400 and "sowingMethod" in r.json()["detail"]
    create.assert_not_called()


def test_complete_with_method_on_tillage_is_400():
    entity = {"status": {"value": "incomplete"}, "operationType": {"value": "tillage"},
              "tillageType": {"value": "ploughing"}, "hasAgriParcel": {"object": "urn:p"}}
    with patch("app.api.operations._get_or_404", return_value=entity), \
         patch("app.api.operations.complete_operation") as complete:
        r = client.post("/api/field-operations/operations/op1/complete",
                        json={"sowingMethod": "direct"}, headers=H)
    assert r.status_code == 400
    complete.assert_not_called()


def test_complete_sowing_with_method_passes_it_through():
    entity = {"status": {"value": "incomplete"}, "operationType": {"value": "sowing"},
              "cropType": {"value": "wheat"}, "variety": {"value": "v"}, "seedingRate": {"value": 180},
              "hasAgriParcel": {"object": "urn:p"}}
    with patch("app.api.operations._get_or_404", return_value=entity), \
         patch("app.api.operations.enforce_spraying_validation"), \
         patch("app.api.operations.complete_operation", return_value={}) as complete:
        r = client.post("/api/field-operations/operations/op1/complete",
                        json={"sowingMethod": "direct"}, headers=H)
    assert r.status_code == 200
    assert complete.call_args.kwargs["extra_attrs"] == {"sowingMethod": "direct"}


def test_work_order_with_unknown_method_is_400():
    with patch("app.api.operations.create_external_work_order") as create:
        r = client.post("/api/field-operations/work-orders", json={**BODY, "sowingMethod": "no-till"}, headers=H)
    assert r.status_code == 400 and "sowingMethod" in r.json()["detail"]
    create.assert_not_called()
