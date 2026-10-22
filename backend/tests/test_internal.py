"""Tests for internal endpoints."""
import os
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestSetupParcel:
    def test_missing_secret_returns_403(self):
        resp = client.post("/internal/setup-parcel", json={"parcel_id": "p1"})
        assert resp.status_code == 403

    def test_wrong_secret_returns_403(self):
        resp = client.post(
            "/internal/setup-parcel",
            json={"parcel_id": "p1"},
            headers={"X-Internal-Service-Secret": "wrong"},
        )
        assert resp.status_code == 403

    def test_valid_secret_returns_200(self):
        os.environ["INTERNAL_SERVICE_SECRET"] = "test-secret"
        resp = client.post(
            "/internal/setup-parcel",
            json={"parcel_id": "urn:ngsi-ld:AgriParcel:t:p1"},
            headers={
                "X-Internal-Service-Secret": "test-secret",
                "X-Tenant-ID": "test-tenant",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["setup_status"] == "ok"
        assert data["module"] == "field-operations"
        del os.environ["INTERNAL_SERVICE_SECRET"]

    def test_missing_parcel_id_returns_400(self):
        os.environ["INTERNAL_SERVICE_SECRET"] = "test-secret"
        resp = client.post(
            "/internal/setup-parcel",
            json={},
            headers={"X-Internal-Service-Secret": "test-secret"},
        )
        assert resp.status_code == 400
        del os.environ["INTERNAL_SERVICE_SECRET"]


class TestDeactivateParcel:
    def test_deactivate_requires_secret(self):
        resp = client.post("/internal/deactivate-parcel", json={"parcel_id": "p1"})
        assert resp.status_code == 403


class TestHealth:
    def test_healthz(self):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_readyz(self):
        resp = client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}
