"""Signed nutrient-plan summary for the notebook (RD 1051/2022 art. 5.1.a)."""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import plan_summary as route
from app.main import app
from app.services import fast_client

P1 = "urn:ngsi-ld:AgriParcel:p1"
HEADERS = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u1", "X-User-Roles": "Farmer"}
SUMMARY = {"plan_id": "pid", "version": 1, "campaign": 2027, "signed_at": "2026-10-20T08:00:00+00:00",
           "snapshot_sha256": "ab" * 32, "signature": {"kind": "advisor", "name": "A", "registration_number": "X"},
           "sheets": [{"key": "wheat", "crop_eppo": "TRZAX", "previous_crop_eppo": "HORVX",
                       "expected_yield_kg_ha": 5600.0, "n_kg_ha": {"min": 100, "avg": 130, "max": 160},
                       "p2o5_kg_ha": 45.0, "k2o_kg_ha": 30.0}]}


def run(coro):
    return asyncio.run(coro)


def transport(status, body=None, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body if body is not None else {})
    return httpx.MockTransport(handler)


def test_not_configured(monkeypatch):
    monkeypatch.setenv("FAST_API_URL", "")
    assert run(fast_client.plan_summary("tenant-a", P1, 2027)) == {"status": "not_configured"}


def test_ok_sends_tenant_parcel_campaign_and_the_secret(monkeypatch):
    monkeypatch.setenv("FAST_API_URL", "http://fast.test/api/fast/")
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s3")
    seen = []
    out = run(fast_client.plan_summary("tenant-a", P1, 2027,
                                       transport=transport(200, SUMMARY, seen)))
    assert out == {"status": "ok", "summary": SUMMARY}
    (req,) = seen
    assert str(req.url).startswith("http://fast.test/api/fast/internal/plans/summary?")
    assert req.url.params["tenant_id"] == "tenant-a" and req.url.params["parcel_id"] == P1
    assert req.url.params["campaign"] == "2027" and req.headers["X-Internal-Service-Secret"] == "s3"


def test_no_plan(monkeypatch):
    monkeypatch.setenv("FAST_API_URL", "http://fast.test/api/fast")
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s3")
    assert run(fast_client.plan_summary("tenant-a", P1, 2027, transport=transport(404))) == {
        "status": "no_plan"}


@pytest.mark.parametrize("status", [401, 500, 503])
def test_unexpected_answers_are_unavailable(monkeypatch, status):
    monkeypatch.setenv("FAST_API_URL", "http://fast.test/api/fast")
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s3")
    assert run(fast_client.plan_summary("tenant-a", P1, 2027, transport=transport(status))) == {
        "status": "unavailable"}


def test_unreachable_and_missing_secret_are_unavailable(monkeypatch):
    monkeypatch.setenv("FAST_API_URL", "http://fast.test/api/fast")
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s3")

    def boom(request):
        raise httpx.ConnectError("down")
    assert run(fast_client.plan_summary("tenant-a", P1, 2027,
                                        transport=httpx.MockTransport(boom)))["status"] == "unavailable"
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "")
    assert run(fast_client.plan_summary("tenant-a", P1, 2027,
                                        transport=transport(200, SUMMARY)))["status"] == "unavailable"


def test_route_uses_the_authenticated_tenant(monkeypatch):
    calls = []

    async def fake(tenant_id, parcel_id, campaign, **_):
        calls.append((tenant_id, parcel_id, campaign))
        return {"status": "no_plan"}
    monkeypatch.setattr(route.fast_client, "plan_summary", fake)
    client = TestClient(app)
    r = client.get("/api/field-operations/plan-summary",
                   params={"parcel_id": P1, "campaign": 2027, "tenant_id": "tenant-b"},
                   headers=HEADERS)
    assert r.status_code == 200 and r.json() == {"status": "no_plan"}
    assert calls == [("tenant-a", P1, 2027)]


@pytest.mark.parametrize("params", [{"parcel_id": P1, "campaign": 1999},
                                    {"parcel_id": "not a urn", "campaign": 2027},
                                    {"campaign": 2027}])
def test_route_validates(params):
    assert TestClient(app).get("/api/field-operations/plan-summary", params=params,
                               headers=HEADERS).status_code == 422


def test_route_needs_auth_headers_and_a_reading_role():
    client = TestClient(app)
    url = "/api/field-operations/plan-summary"
    params = {"parcel_id": P1, "campaign": 2027}
    assert client.get(url, params=params).status_code == 401
    other = {**HEADERS, "X-User-Roles": "SomethingElse"}
    assert client.get(url, params=params, headers=other).status_code == 403
