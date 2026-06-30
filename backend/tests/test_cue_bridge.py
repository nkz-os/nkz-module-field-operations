"""cue_bridge must call CUE under the /api/modules/cue prefix with internal-service auth."""
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.cue_bridge as cb


def _client():
    a = FastAPI()
    a.include_router(cb.router)
    return TestClient(a)


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _FakeAsyncClient:
    """Captures the last get/post call into `calls`."""

    calls: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None):
        _FakeAsyncClient.calls.append(("GET", url, params, headers))
        return _Resp([{"nombre_comercial": "Prod A"}])

    async def post(self, url, json=None, headers=None):
        _FakeAsyncClient.calls.append(("POST", url, json, headers))
        return _Resp({"id": "siex-1"})


def _reset():
    _FakeAsyncClient.calls = []


def test_list_products_uses_prefixed_path_and_internal_auth():
    _reset()
    with patch.object(cb.httpx, "AsyncClient", _FakeAsyncClient):
        r = _client().get(
            "/api/field-operations/cue/productos-autorizados?cultivo=trigo",
            headers={"X-Tenant-ID": "montiko"},
        )
    assert r.status_code == 200
    method, url, params, headers = _FakeAsyncClient.calls[-1]
    assert url.endswith("/api/modules/cue/productos-ropo")
    assert headers["X-Tenant-ID"] == "montiko"
    assert headers["X-Internal-Service-Secret"] == cb.INTERNAL_SERVICE_SECRET


def test_product_detail_routes_by_tipo():
    _reset()
    with patch.object(cb.httpx, "AsyncClient", _FakeAsyncClient):
        r = _client().get(
            "/api/field-operations/cue/productos-autorizados/ES-12345?tipo=fitosanitario",
            headers={"X-Tenant-ID": "montiko"},
        )
    assert r.status_code == 200
    _, url, _, headers = _FakeAsyncClient.calls[-1]
    assert url.endswith("/api/modules/cue/productos-ropo/ES-12345")
    assert "X-Internal-Service-Secret" in headers


def test_siex_register_uses_prefixed_path_and_internal_auth():
    _reset()
    entity = {
        "id": "urn:ngsi-ld:AgriParcelOperation:montiko:op1",
        "operationType": {"value": "spraying"},
        "startedAt": {"value": {"@value": "2026-06-30T08:00:00Z"}},
    }
    with patch.object(cb.httpx, "AsyncClient", _FakeAsyncClient), \
         patch("app.orion_ops.get_entity", return_value=entity), \
         patch("app.orion_ops.update_entity_attrs", return_value=None):
        r = _client().post(
            "/api/field-operations/cue/operations/op1/registrar-siex",
            headers={"X-Tenant-ID": "montiko", "X-User-Roles": "field_manager"},
        )
    assert r.status_code == 200
    method, url, body, headers = _FakeAsyncClient.calls[-1]
    assert method == "POST"
    assert url.endswith("/api/modules/cue/tratamientos")
    assert headers["X-Internal-Service-Secret"] == cb.INTERNAL_SERVICE_SECRET
