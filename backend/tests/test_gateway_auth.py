"""User routes trust only a gateway-signed identity (X-Auth-Signature)."""
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from nkz_platform_sdk import auth as sdk_auth
from nkz_platform_sdk.crypto import generate_hmac_signature

from app.auth import ensure_signature_enforced, gateway_identity
from app.main import app

SECRET = "test-hmac-secret"
TOKEN = "user-jwt"
PUBLIC = {"/healthz", "/readyz", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def _dependency_calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _dependency_calls(dep)


def _guarded(route) -> bool:
    calls = set(_dependency_calls(route.dependant))
    # plan-summary already verifies the signature with the SDK's require_auth.
    return gateway_identity in calls or any(
        getattr(c, "__qualname__", "").startswith("require_auth") for c in calls)


def test_every_user_route_requires_gateway_identity():
    unguarded = [r.path for r in app.routes if isinstance(r, APIRoute)
                 and r.path not in PUBLIC and not r.path.startswith("/internal/")
                 and not _guarded(r)]
    assert unguarded == []


@pytest.fixture
def signed_mode(monkeypatch):
    monkeypatch.setattr(sdk_auth, "REQUIRE_HMAC", True)
    monkeypatch.setattr(sdk_auth, "HMAC_SECRET", SECRET)


@pytest.fixture
def client():
    return TestClient(app)


def _headers(tenant, signature=None):
    h = {"X-Tenant-ID": tenant, "X-User-ID": "u1", "Authorization": f"Bearer {TOKEN}"}
    if signature is not None:
        h["X-Auth-Signature"] = signature
    return h


def test_unsigned_identity_rejected(signed_mode, client):
    assert client.get("/api/field-operations/operations", headers=_headers("tenant-a")).status_code == 401


def test_signature_for_other_tenant_rejected(signed_mode, client):
    sig = generate_hmac_signature(SECRET, TOKEN, "tenant-b")
    assert client.get("/api/field-operations/operations", headers=_headers("tenant-a", sig)).status_code == 401


def test_missing_identity_rejected(client):
    assert client.get("/api/field-operations/operations").status_code == 401


def test_startup_refuses_without_signature_check(monkeypatch):
    monkeypatch.setattr(sdk_auth, "REQUIRE_HMAC", False)
    monkeypatch.setattr(sdk_auth, "HMAC_SECRET", SECRET)
    with pytest.raises(RuntimeError):
        ensure_signature_enforced()
    monkeypatch.setattr(sdk_auth, "REQUIRE_HMAC", True)
    monkeypatch.setattr(sdk_auth, "HMAC_SECRET", "")
    with pytest.raises(RuntimeError):
        ensure_signature_enforced()


def test_startup_accepts_enforced_signature(signed_mode):
    ensure_signature_enforced()
