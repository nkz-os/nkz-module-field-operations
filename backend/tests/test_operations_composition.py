"""Composition fields through the operations API (Orion mocked)."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
HEADERS = {"X-User-ID": "u1", "X-Tenant-ID": "tenant-1", "X-User-Roles": "field_manager"}
OP_ID = "urn:ngsi-ld:AgriParcelOperation:t1:abc"
PARCEL = "urn:ngsi-ld:AgriParcel:t1:p1"
BASE = "/api/field-operations"


def _entity(op_type="fertilization", **attrs):
    entity = {
        "id": OP_ID, "type": "AgriParcelOperation",
        "status": {"type": "Property", "value": "incomplete"},
        "operationType": {"type": "Property", "value": op_type},
        "hasAgriParcel": {"type": "Relationship", "object": PARCEL},
    }
    entity.update({k: {"type": "Property", "value": v} for k, v in attrs.items()})
    return entity


def _create_body(**extra):
    return {"parcel_id": PARCEL, "operation_type": "fertilization", "work_order": "WO-1",
            "operator": "op", **extra}


@patch("app.api.operations.create_operation")
def test_create_stores_contents_as_percent_properties(mock_create):
    mock_create.return_value = {"id": OP_ID}
    resp = client.post(f"{BASE}/operations", headers=HEADERS,
                       json=_create_body(fertilizerRate=300, nitrogenContent=15, nitrogenForm="ammoniacal"))
    assert resp.status_code == 200
    kwargs = mock_create.call_args.kwargs
    assert kwargs["nitrogenContent"] == {"value": 15.0, "unitCode": "P1"}
    assert kwargs["nitrogenForm"] == "ammoniacal"
    assert kwargs["fertilizerRate"] == 300


@patch("app.api.operations.create_operation")
def test_create_rejects_bad_composition_with_422(mock_create):
    resp = client.post(f"{BASE}/operations", headers=HEADERS, json=_create_body(nitrogenContent="15"))
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_fertilizer_composition"
    mock_create.assert_not_called()


@patch("app.api.operations.enforce_spraying_validation")
@patch("app.api.operations.create_external_work_order")
def test_work_order_normalizes_composition(mock_wo, _validation):
    mock_wo.return_value = {"id": OP_ID}
    resp = client.post(f"{BASE}/work-orders", headers=HEADERS,
                       json=_create_body(work_order="EXT-1", potassiumOxideContent=60))
    assert resp.status_code == 200
    assert mock_wo.call_args.kwargs["potassiumOxideContent"] == {"value": 60.0, "unitCode": "P1"}


@patch("app.api.operations.enforce_spraying_validation")
@patch("app.api.operations.create_external_work_order")
def test_work_order_rejects_composition_on_sowing(mock_wo, _validation):
    resp = client.post(f"{BASE}/work-orders", headers=HEADERS,
                       json=_create_body(operation_type="sowing", work_order="EXT-2", nitrogenContent=10))
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_fertilizer_composition"
    mock_wo.assert_not_called()


@patch("app.api.operations.enforce_spraying_validation")
@patch("app.api.operations.complete_operation")
@patch("app.api.operations.get_entity")
def test_complete_writes_normalized_contents(mock_get, mock_complete, _validation):
    mock_get.return_value = _entity(fertilizerType="NPK", fertilizerRate=300)
    mock_complete.return_value = {}
    resp = client.post(f"{BASE}/operations/{OP_ID}/complete", headers=HEADERS,
                       json={"nitrogenContent": 27, "phosphorusPentoxideContent": None, "nitrogenForm": "nitric"})
    assert resp.status_code == 200
    assert mock_complete.call_args.kwargs["extra_attrs"] == {
        "nitrogenContent": {"value": 27.0, "unitCode": "P1"}, "nitrogenForm": "nitric",
    }


@patch("app.api.operations.enforce_spraying_validation")
@patch("app.api.operations.complete_operation")
@patch("app.api.operations.get_entity")
def test_complete_rejects_a_grade_over_100(mock_get, mock_complete, _validation):
    mock_get.return_value = _entity(fertilizerType="NPK", fertilizerRate=300)
    resp = client.post(f"{BASE}/operations/{OP_ID}/complete", headers=HEADERS,
                       json={"nitrogenContent": 46, "phosphorusPentoxideContent": 46, "potassiumOxideContent": 46})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_fertilizer_composition"
    mock_complete.assert_not_called()


@patch("app.api.operations.enforce_spraying_validation")
@patch("app.api.operations.complete_operation")
@patch("app.api.operations.get_entity")
def test_complete_of_a_sowing_is_unchanged(mock_get, mock_complete, _validation):
    mock_get.return_value = _entity("sowing", cropType="wheat", variety="x", seedingRate=180)
    mock_complete.return_value = {}
    body = {"irrigationRegime": "rainfed"}
    resp = client.post(f"{BASE}/operations/{OP_ID}/complete", headers=HEADERS, json=body)
    assert resp.status_code == 200
    assert mock_complete.call_args.kwargs["extra_attrs"] == body


@patch("app.api.operations.enforce_spraying_validation")
@patch("app.api.operations.complete_operation")
@patch("app.api.operations.get_entity")
def test_complete_rejects_a_grade_over_100_against_stored_contents(mock_get, mock_complete, _validation):
    mock_get.return_value = _entity(fertilizerType="NPK", fertilizerRate=300, nitrogenContent=46)
    resp = client.post(f"{BASE}/operations/{OP_ID}/complete", headers=HEADERS,
                       json={"phosphorusPentoxideContent": 46, "potassiumOxideContent": 46})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_fertilizer_composition"
    mock_complete.assert_not_called()
