"""Crop-cycle runtime: Orion receiver, queue, sweep, subscriptions — inert unless enabled."""
import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import crop_cycles_runtime as rt

P = "urn:ngsi-ld:AgriParcel:p1"
SECRET = "test-secret"
NOTE = {"data": [{"type": "AgriParcelOperation", "hasAgriParcel": P}]}
HEADERS = {"X-Internal-Service-Secret": SECRET, "NGSILD-Tenant": "tenant-a"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", SECRET)
    monkeypatch.setattr(config, "INTERNAL_SERVICE_SECRET", SECRET)
    monkeypatch.setattr(config, "CROP_CYCLES_WRITER_ENABLED", True)
    monkeypatch.setattr(rt, "_registrar", None)
    rt._pending.clear()
    yield
    rt._pending.clear()


def test_receiver_requires_token():
    client = TestClient(app)
    assert client.post("/internal/notify/crop-cycles", json=NOTE).status_code == 401
    r = client.post("/internal/notify/crop-cycles", json=NOTE, headers=HEADERS)
    assert r.status_code == 204 and r.content == b""


def test_flag_off_drops_notifications(monkeypatch):
    monkeypatch.setattr(config, "CROP_CYCLES_WRITER_ENABLED", False)
    r = TestClient(app).post("/internal/notify/crop-cycles", json=NOTE, headers=HEADERS)
    assert r.status_code == 204 and rt._pending == set()


@pytest.mark.asyncio
async def test_burst_is_deduplicated(monkeypatch):
    client = TestClient(app)
    for _ in range(3):
        assert client.post("/internal/notify/crop-cycles", json=NOTE, headers=HEADERS).status_code == 204
    assert rt._pending == {("tenant-a", P)}
    calls = []

    async def fake_reconcile(client_, tenant, parcel, at=None):
        calls.append((tenant, parcel))
        return []

    monkeypatch.setattr(rt, "reconcile_parcel", fake_reconcile)
    await rt.drain()
    assert calls == [("tenant-a", P)] and rt._pending == set()


@pytest.mark.asyncio
async def test_one_failing_parcel_does_not_drop_the_batch(monkeypatch):
    rt._pending.update({("tenant-a", P), ("tenant-a", "urn:ngsi-ld:AgriParcel:p2")})
    done = []

    async def fake_reconcile(client_, tenant, parcel, at=None):
        if parcel == P:
            raise RuntimeError("broker hiccup")
        done.append(parcel)
        return []

    monkeypatch.setattr(rt, "reconcile_parcel", fake_reconcile)
    await rt.drain()
    assert done == ["urn:ngsi-ld:AgriParcel:p2"]


def test_registrar_declares_both_types_without_throttling(monkeypatch):
    monkeypatch.setattr(config, "CROP_CYCLES_NOTIFY_URL", "http://fo:8420/internal/notify/crop-cycles")
    reg = rt.get_registrar()
    assert reg.module_name == "field-operations"
    assert reg.notification_url == "http://fo:8420/internal/notify/crop-cycles"
    bodies = [reg._body(s, "tenant-a") for s in reg._subs]
    assert [b["entities"][0]["type"] for b in bodies] == ["AgriCrop", "AgriParcelOperation"]
    assert all("throttling" not in b for b in bodies)


def test_no_registrar_without_secret(monkeypatch):
    monkeypatch.setattr(config, "INTERNAL_SERVICE_SECRET", "")
    assert rt.get_registrar() is None


@pytest.mark.asyncio
async def test_subscriptions_untouched_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "CROP_CYCLES_WRITER_ENABLED", False)
    assert await rt.reconcile_subscriptions() is None


@pytest.mark.asyncio
async def test_sweep_reconciles_parcels_of_enabled_tenants(monkeypatch):
    from nkz_platform_sdk.installations import TenantInstallations

    async def fake_installed(module_id, **kw):
        assert module_id == "field-operations"
        return TenantInstallations(module_id, ("tenant-a",), ("tenant-b",), ())

    async def fake_list(client_):
        return [P]

    seen = []

    async def fake_reconcile(client_, tenant, parcel, at=None):
        seen.append((tenant, parcel))
        return []

    monkeypatch.setattr(rt, "installed_tenants", fake_installed)
    monkeypatch.setattr(rt, "list_parcels", fake_list)
    monkeypatch.setattr(rt, "reconcile_parcel", fake_reconcile)
    stats = await rt.sweep_once()
    # The sweep queues; the worker is the only one that reconciles, so a sweep
    # and a notification never write the same parcel at once.
    assert seen == [] and rt._pending == {("tenant-a", P)} and stats["queued"] == 1


@pytest.mark.asyncio
async def test_sweep_skips_when_platform_unavailable(monkeypatch):
    from nkz_platform_sdk.installations import InstalledTenantsUnavailable

    async def boom(module_id, **kw):
        raise InstalledTenantsUnavailable("503")

    seen = []

    async def fake_reconcile(*a, **k):
        seen.append(a)
        return []

    monkeypatch.setattr(rt, "installed_tenants", boom)
    monkeypatch.setattr(rt, "reconcile_parcel", fake_reconcile)
    stats = await rt.sweep_once()
    assert stats["skipped"] == "unavailable" and seen == []


def test_lifecycle_route_mounted():
    assert TestClient(app).post("/internal/lifecycle").status_code == 401


@pytest.mark.asyncio
async def test_drain_survives_a_client_that_cannot_be_built(monkeypatch):
    rt._pending.update({("tenant-a", P), ("tenant-b", P)})
    done = []

    def flaky_client(tenant):
        if tenant == "tenant-a":
            raise RuntimeError("no client")
        return rt.OrionClient(tenant, base_url="http://orion:1026")

    async def fake_reconcile(client_, tenant, parcel, at=None):
        done.append(tenant)
        return []

    monkeypatch.setattr(rt, "_client", flaky_client)
    monkeypatch.setattr(rt, "reconcile_parcel", fake_reconcile)
    await rt.drain()
    assert done == ["tenant-b"] and rt._pending == set()


@pytest.mark.parametrize("body", [[1, 2], {"data": {"type": "AgriCrop"}}, {"data": ["x", None]}])
def test_receiver_tolerates_odd_bodies(body):
    r = TestClient(app).post("/internal/notify/crop-cycles", json=body, headers=HEADERS)
    assert r.status_code == 204 and rt._pending == set()
