"""Weekly report contribution (contract: version 1, internal route)."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import VALID_OPERATION_TYPES
from app.main import app
from app.services import weekly_report

client = TestClient(app)
SECRET = "test-secret"
HEADERS = {"X-Internal-Service-Secret": SECRET}
URL = "/internal/weekly-report"
PARCEL = "urn:ngsi-ld:AgriParcel:acme:abcdef1234567890"
NAMED = "urn:ngsi-ld:AgriParcel:acme:named-parcel"


def _op(op_id, status="planned", op_type="irrigation", parcel=PARCEL, planned=None):
    op = {"id": op_id, "type": "AgriParcelOperation", "status": status,
          "operationType": op_type, "hasAgriParcel": parcel}
    if planned is not None:
        op["plannedDate"] = planned
    return op


def _fake_ops(by_status):
    def fake(tenant_id, status=None, limit=100, offset=0, **kw):
        rows = by_status.get(status, [])
        return rows[offset:offset + limit]
    return fake


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", SECRET)


def _get(by_status, parcels=None, **params):
    parcels = {NAMED: "Olive grove"} if parcels is None else parcels
    q = {"tenant_id": "acme", "week_start": "2026-11-09", **params}
    with patch.object(weekly_report, "query_operations", _fake_ops(by_status)), \
         patch.object(weekly_report, "query_parcel_names", lambda t: parcels):
        return client.get(URL, params=q, headers=HEADERS)


def test_planned_and_issued_included():
    r = _get({"planned": [_op("op1")], "issued": [_op("op2", "issued")]})
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1 and body["complete"] is True
    assert {t["id"] for t in body["tasks"]} == {"op1", "op2"}
    assert body["changes"] == [] and body["figures"] == []


def test_completed_cancelled_excluded():
    rows = [_op("c1", "completed"), _op("c2", "cancelled"), _op("p1")]
    r = _get({"planned": rows})
    assert [t["id"] for t in r.json()["tasks"]] == ["p1"]


def test_planned_date_mapping_normalized_and_plain():
    ops = [
        _op("a", planned={"@type": "DateTime", "@value": "2026-11-12T00:00:00Z"}),
        _op("b", planned="2026-11-13T08:00:00Z"),
        _op("c", planned={"type": "Property", "value": {"@type": "DateTime", "@value": "2026-11-14T00:00:00Z"}}),
        _op("d"),
        _op("e", planned="not a date"),
    ]
    tasks = {t["id"]: t for t in _get({"planned": ops}).json()["tasks"]}
    assert tasks["a"]["when"] == {"type": "date", "date": "2026-11-12"}
    assert tasks["b"]["when"] == {"type": "date", "date": "2026-11-13"}
    assert tasks["c"]["when"] == {"type": "date", "date": "2026-11-14"}
    assert tasks["d"]["when"] == {"type": "undated", "date": None}
    assert tasks["e"]["when"] == {"type": "undated", "date": None}


def test_far_future_task_not_filtered_here():
    far = _op("far", planned="2027-03-01T00:00:00Z")
    assert [t["id"] for t in _get({"planned": [far]}).json()["tasks"]] == ["far"]


def test_all_operation_types_have_text():
    assert len(VALID_OPERATION_TYPES) == 9
    ops = [_op(f"o{i}", op_type=t) for i, t in enumerate(VALID_OPERATION_TYPES)]
    for task in _get({"planned": ops}).json()["tasks"]:
        for lang in ("es", "eu", "en"):
            assert task["text"][lang]["title"].strip()
            assert task["text"][lang]["why"].strip()
            assert "urn:" not in task["text"][lang]["title"]


def test_issued_has_review_wording():
    t = _get({"issued": [_op("i", "issued")]}).json()["tasks"][0]
    p = _get({"planned": [_op("p")]}).json()["tasks"][0]
    assert t["text"]["en"]["why"] != p["text"]["en"]["why"]


def test_parcel_name_resolved_and_fallback_never_urn():
    ops = [_op("n", parcel=NAMED), _op("u", parcel=PARCEL),
           _op("d", parcel={"type": "Relationship", "object": NAMED})]
    tasks = {t["id"]: t for t in _get({"planned": ops}).json()["tasks"]}
    assert tasks["n"]["subject"] == {"type": "parcel", "id": NAMED, "name": "Olive grove"}
    assert tasks["d"]["subject"]["name"] == "Olive grove"
    assert tasks["u"]["subject"]["name"] == "abcdef12"
    assert "urn:" not in tasks["u"]["subject"]["name"]


def _no_text_codes(task):
    for lang in ("es", "eu", "en"):
        for v in task["text"][lang].values():
            assert v.strip() and "urn:" not in v and "{" not in v


def test_operation_without_parcel_shown_generic():
    op = _op("x")
    del op["hasAgriParcel"]
    body = _get({"planned": [op, _op("y")]}).json()
    t = {t["id"]: t for t in body["tasks"]}["x"]
    assert t["subject"] == {"type": "farm", "id": "", "name": ""}
    assert t["link"] is None
    assert t["text"]["es"]["title"] == "Operación pendiente sin parcela asignada"
    _no_text_codes(t)
    assert body["complete"] is True and len(body["tasks"]) == 2


def test_unknown_type_shown_with_parcel_name():
    body = _get({"planned": [_op("u", op_type="weird_type", parcel=NAMED)]}).json()
    t = body["tasks"][0]
    assert t["kind"] == "other"
    assert t["text"]["es"]["title"] == "Operación pendiente en Olive grove"
    assert "weird_type" not in str(t["text"])
    _no_text_codes(t)
    assert body["complete"] is True


def test_missing_type_shown_too():
    op = _op("m")
    del op["operationType"]
    assert [t["id"] for t in _get({"planned": [op]}).json()["tasks"]] == ["m"]


def test_row_without_id_marks_incomplete(caplog):
    bad = _op("z")
    del bad["id"]
    body = _get({"planned": [bad, _op("ok")]}).json()
    assert [t["id"] for t in body["tasks"]] == ["ok"]
    assert body["complete"] is False


def test_duplicate_across_pages_deduped(monkeypatch):
    monkeypatch.setattr(weekly_report, "PAGE", 2)
    rows = [_op("a"), _op("b"), _op("b"), _op("c")]
    ids = [t["id"] for t in _get({"planned": rows}).json()["tasks"]]
    assert sorted(ids) == ["a", "b", "c"]


def test_paging_reads_every_page(monkeypatch):
    monkeypatch.setattr(weekly_report, "PAGE", 2)
    rows = [_op(f"p{i}") for i in range(5)]
    assert len(_get({"planned": rows}).json()["tasks"]) == 5


def test_orion_operations_failure_502():
    def boom(*a, **k):
        raise RuntimeError("Orion-LD query failed (500)")
    with patch.object(weekly_report, "query_operations", boom), \
         patch.object(weekly_report, "query_parcel_names", lambda t: {}):
        r = client.get(URL, params={"tenant_id": "acme", "week_start": "2026-11-09"}, headers=HEADERS)
    assert r.status_code == 502


def test_orion_parcels_failure_502():
    def boom(t):
        raise RuntimeError("Orion-LD query failed (503)")
    with patch.object(weekly_report, "query_operations", _fake_ops({})), \
         patch.object(weekly_report, "query_parcel_names", boom):
        r = client.get(URL, params={"tenant_id": "acme", "week_start": "2026-11-09"}, headers=HEADERS)
    assert r.status_code == 502


def test_non_orion_error_is_500_not_200():
    local = TestClient(app, raise_server_exceptions=False)
    with patch.object(weekly_report, "query_operations", _fake_ops({})), \
         patch.object(weekly_report, "query_parcel_names", lambda t: 1 / 0):
        r = local.get(URL, params={"tenant_id": "acme", "week_start": "2026-11-09"}, headers=HEADERS)
    assert r.status_code == 500


def test_network_error_is_502():
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("down")
    with patch.object(weekly_report, "query_operations", boom), \
         patch.object(weekly_report, "query_parcel_names", lambda t: {}):
        r = client.get(URL, params={"tenant_id": "acme", "week_start": "2026-11-09"}, headers=HEADERS)
    assert r.status_code == 502


def test_secret_required(monkeypatch):
    q = {"tenant_id": "acme", "week_start": "2026-11-09"}
    assert client.get(URL, params=q).status_code == 401
    assert client.get(URL, params=q, headers={"X-Internal-Service-Secret": "bad"}).status_code == 401
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET")
    assert client.get(URL, params=q, headers=HEADERS).status_code == 401


@pytest.mark.parametrize("params", [
    {"week_start": "2026-11-09"},
    {"tenant_id": "Bad Tenant!", "week_start": "2026-11-09"},
    {"tenant_id": "acme"},
    {"tenant_id": "acme", "week_start": "2026-11-10"},
    {"tenant_id": "acme", "week_start": "nope"},
])
def test_bad_params_400(params):
    assert client.get(URL, params=params, headers=HEADERS).status_code == 400


def test_query_operations_offset_opt_in():
    """offset defaults to 0 and is only sent when set (existing callers unchanged)."""
    from app import orion_ops

    seen = []

    class Resp:
        status_code = 200
        def json(self): return []

    class Sess:
        def get(self, url, params=None, **kw):
            seen.append(params); return Resp()

    class C:
        _session = Sess(); timeout = 1
        def _url(self, p): return p
        def _headers(self, c): return {}

    with patch.object(orion_ops, "_get_client", lambda t: C()):
        orion_ops.query_operations("acme", status="planned")
        orion_ops.query_operations("acme", status="planned", offset=1000)
    assert "offset" not in seen[0]
    assert seen[1]["offset"] == 1000
