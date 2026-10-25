"""Daily bridge: water meter counters -> one completed irrigation operation per parcel-day."""
from datetime import date, datetime, timezone

import httpx
import pytest

import app.services.irrigation_bridge as bridge
from app.services.irrigation_bridge import daily_volumes, run_bridge_for_tenant

TODAY = date(2026, 10, 25)
DAY = date(2026, 10, 24)
PARCEL = "urn:ngsi-ld:AgriParcel:p-1"
OP_ID = "urn:ngsi-ld:AgriParcelOperation:tenant-a:irrigation-sensor-p-1-20261024"


def _t(d: date, h: int, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=timezone.utc)


def _counter(prev_total: float, used: float, day: date = DAY) -> list:
    """Counter readings: one late on the previous day, two on the day itself."""
    prev = date.fromordinal(day.toordinal() - 1)
    return [(_t(prev, 23, 50), prev_total), (_t(day, 8), prev_total + used / 2),
            (_t(day, 20), prev_total + used)]


def _device(urn: str, asset=PARCEL, **extra) -> dict:
    d = {"id": urn, "type": "Device", "controlledProperty": ["waterConsumption"]}
    if asset is not None:
        d["controlledAsset"] = asset
    d.update(extra)
    return d


def _not_found(url: str) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", url)
    return httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))


class FakeOrion:
    def __init__(self, devices, parcels, ops=None):
        self.devices, self.parcels, self.ops = devices, parcels, dict(ops or {})
        self.created, self.patched = [], []
        self.context_url = "http://context.test/ctx.json"

    async def query_entities(self, type=None, limit=100, offset=0, options=None, **kw):
        assert type == "Device"
        return self.devices[offset:offset + limit]

    async def get_entity(self, entity_id, options=None):
        if entity_id in self.parcels:
            return self.parcels[entity_id]
        if entity_id in self.ops:
            return self.ops[entity_id]
        raise _not_found(entity_id)

    async def create_entity(self, entity):
        self.created.append(entity)
        return {"id": entity["id"], "status": "created"}

    async def close(self):
        pass


@pytest.fixture
def world(monkeypatch):
    state = {"readings": {}}

    def install(devices, parcels=None, ops=None, readings=None):
        orion = FakeOrion(devices, parcels if parcels is not None else {PARCEL: {"id": PARCEL, "area": 0.5}},
                          ops)
        state["orion"] = orion
        state["readings"] = readings or {}
        monkeypatch.setattr(bridge, "_orion", lambda tenant_id: orion)

        async def fake_patch(client, entity_id, attrs):
            client.patched.append((entity_id, attrs))
        monkeypatch.setattr(bridge, "_merge_patch", fake_patch)

        async def fake_fetch(tenant_id, device_urn, start, end):
            return state["readings"].get(device_urn, [])
        monkeypatch.setattr(bridge, "fetch_counter_readings", fake_fetch)
        return orion
    return install


def _sensor_op(volume_m3: float, per_ha: float, status="completed", log=None) -> dict:
    return {
        "id": OP_ID, "type": "AgriParcelOperation",
        "status": {"type": "Property", "value": status},
        "dataSource": {"type": "Property", "value": "sensor"},
        "waterVolume": {"type": "Property", "value": volume_m3, "unitCode": "MTQ"},
        "waterPerHectare": {"type": "Property", "value": per_ha},
        "modificationLog": {"type": "Property", "value": log if log is not None else []},
    }


# --- daily_volumes -------------------------------------------------------------------------

def test_daily_volumes_counter_delta():
    prev = date(2026, 10, 23)
    readings = [(_t(prev, 23, 50), 100000.0), (_t(DAY, 8), 104000.0), (_t(DAY, 20), 112500.0)]
    assert daily_volumes(readings, [DAY]) == {DAY: 12500.0}


def test_daily_volumes_reset_or_gap_skips():
    prev = date(2026, 10, 23)
    reset = [(_t(prev, 23, 50), 100000.0), (_t(DAY, 8), 50.0)]
    assert daily_volumes(reset, [DAY]) == {}
    no_before = [(_t(DAY, 8), 104000.0), (_t(DAY, 20), 112500.0)]
    assert daily_volumes(no_before, [DAY]) == {}
    # Other days are unaffected by one bad day.
    nxt = date(2026, 10, 25)
    mixed = reset + [(_t(nxt, 9), 1050.0)]
    assert daily_volumes(mixed, [DAY, nxt]) == {nxt: 1000.0}


def test_daily_volumes_stale_boundary_skips():
    # The previous reading is two days old: the delta spans more than the day.
    old = date(2026, 10, 22)
    assert daily_volumes([(_t(old, 12), 100.0), (_t(DAY, 12), 600.0)], [DAY]) == {}


# --- run_bridge_for_tenant -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_bridge_creates_one_operation_per_parcel_day(world):
    m1, m2 = "urn:ngsi-ld:Device:m-2", "urn:ngsi-ld:Device:m-1"
    orion = world([_device(m1, asset=[PARCEL, "urn:ngsi-ld:AgriParcel:p-9"]), _device(m2)],
                  readings={m1: _counter(10000, 2000), m2: _counter(500, 3000)})
    counts = await run_bridge_for_tenant("tenant-a", TODAY)

    assert counts["created"] == 1
    assert len(orion.created) == 1
    op = orion.created[0]
    assert op["id"] == OP_ID
    assert op["type"] == "AgriParcelOperation"
    assert op["hasAgriParcel"] == {"type": "Relationship", "object": PARCEL}
    assert op["operationType"]["value"] == "irrigation"
    assert op["status"]["value"] == "completed"
    assert op["dataSource"]["value"] == "sensor"
    assert op["operator"]["value"] == "sensor"
    assert op["waterPerHectare"]["value"] == 10000
    assert op["waterVolume"] == {"type": "Property", "value": 5.0, "unitCode": "MTQ"}
    assert op["startedAt"]["value"] == {"@type": "DateTime", "@value": "2026-10-24T12:00:00Z"}
    assert op["endedAt"]["value"] == {"@type": "DateTime", "@value": "2026-10-24T12:00:00Z"}
    assert op["observedBy"] == {"type": "Relationship", "object": sorted([m1, m2])}
    assert op["modificationLog"]["value"] == []


@pytest.mark.asyncio
async def test_bridge_reads_parcel_link_names(world):
    m1, m2 = "urn:ngsi-ld:Device:m-1", "urn:ngsi-ld:Device:m-2"
    other = "urn:ngsi-ld:AgriParcel:p-2"
    parcels = {PARCEL: {"id": PARCEL, "area": 1.0}, other: {"id": other, "area": {"@value": 2.0}}}
    orion = world([_device(m1, asset=None, hasAgriParcel=PARCEL),
                   _device(m2, asset=None, refAgriParcel=other)],
                  parcels=parcels, readings={m1: _counter(0, 1000), m2: _counter(0, 1000)})
    counts = await run_bridge_for_tenant("tenant-a", TODAY)
    assert counts["created"] == 2
    by_parcel = {op["hasAgriParcel"]["object"]: op for op in orion.created}
    assert by_parcel[PARCEL]["waterPerHectare"]["value"] == 1000
    assert by_parcel[other]["waterPerHectare"]["value"] == 500


@pytest.mark.asyncio
async def test_bridge_skips_without_owner_or_area(world):
    m1, m2 = "urn:ngsi-ld:Device:m-1", "urn:ngsi-ld:Device:m-2"
    no_area = "urn:ngsi-ld:AgriParcel:p-3"
    parcels = {no_area: {"id": no_area, "area": 0}}
    orion = world([_device(m1, asset=["urn:ngsi-ld:Building:b-1"]), _device(m2, asset=no_area)],
                  parcels=parcels, readings={m1: _counter(0, 1000), m2: _counter(0, 1000)})
    counts = await run_bridge_for_tenant("tenant-a", TODAY)
    assert orion.created == [] and orion.patched == []
    assert counts["created"] == 0
    assert counts["skipped"] >= 2


@pytest.mark.asyncio
async def test_bridge_ignores_other_devices_and_zero_days(world):
    m1, m2 = "urn:ngsi-ld:Device:m-1", "urn:ngsi-ld:Device:t-1"
    orion = world([_device(m1), {"id": m2, "type": "Device", "controlledProperty": "temperature",
                                 "controlledAsset": PARCEL}],
                  readings={m1: _counter(700, 0), m2: _counter(0, 1000)})
    counts = await run_bridge_for_tenant("tenant-a", TODAY)
    assert orion.created == []
    assert counts["created"] == 0


@pytest.mark.asyncio
async def test_bridge_skips_parcel_day_when_one_meter_unknown(world):
    m1, m2 = "urn:ngsi-ld:Device:m-1", "urn:ngsi-ld:Device:m-2"
    orion = world([_device(m1), _device(m2)], readings={m1: _counter(0, 2000), m2: None})
    counts = await run_bridge_for_tenant("tenant-a", TODAY)
    assert orion.created == []
    assert counts["skipped"] >= 1


@pytest.mark.asyncio
async def test_bridge_never_touches_person_decisions(world):
    m1 = "urn:ngsi-ld:Device:m-1"
    cancelled = _sensor_op(5.0, 10000, status="cancelled")
    orion = world([_device(m1)], ops={OP_ID: cancelled}, readings={m1: _counter(0, 6000)})
    await run_bridge_for_tenant("tenant-a", TODAY)
    assert orion.created == [] and orion.patched == []

    # A user's correction; Orion returns a one-entry array unwrapped.
    corrected = _sensor_op(4.0, 8000, log={"field": "waterPerHectare", "by": "user-1", "at": "x"})
    orion = world([_device(m1)], ops={OP_ID: corrected}, readings={m1: _counter(0, 6000)})
    counts = await run_bridge_for_tenant("tenant-a", TODAY)
    assert orion.created == [] and orion.patched == []
    assert counts["skipped"] >= 1


@pytest.mark.asyncio
async def test_bridge_rerun_is_noop(world):
    m1 = "urn:ngsi-ld:Device:m-1"
    existing = _sensor_op(5.0, 10000, log=[{"by": "sensor", "field": "waterVolume"}])
    orion = world([_device(m1)], ops={OP_ID: existing}, readings={m1: _counter(100, 5000)})
    counts = await run_bridge_for_tenant("tenant-a", TODAY)
    assert orion.created == [] and orion.patched == []
    assert counts["unchanged"] == 1


@pytest.mark.asyncio
async def test_bridge_updates_on_late_telemetry(world):
    m1 = "urn:ngsi-ld:Device:m-1"
    orion = world([_device(m1)], ops={OP_ID: _sensor_op(5.0, 10000)}, readings={m1: _counter(0, 6000)})
    counts = await run_bridge_for_tenant("tenant-a", TODAY)
    assert counts["updated"] == 1
    assert orion.created == []
    (entity_id, attrs), = orion.patched
    assert entity_id == OP_ID
    assert attrs["waterVolume"] == {"type": "Property", "value": 6.0, "unitCode": "MTQ"}
    assert attrs["waterPerHectare"]["value"] == 12000
    assert attrs["observedBy"] == {"type": "Relationship", "object": [m1]}
    log = attrs["modificationLog"]["value"]
    assert log[-1]["by"] == "sensor"


@pytest.mark.asyncio
async def test_bridge_loop_survives_errors(monkeypatch):
    from nkz_platform_sdk.installations import TenantInstallations

    async def fake_installed(module_id, **kw):
        assert module_id == "field-operations"
        return TenantInstallations(module_id, ("tenant-a", "tenant-b"), (), ())

    seen = []

    async def fake_run(tenant_id, today):
        seen.append(tenant_id)
        if tenant_id == "tenant-a":
            raise RuntimeError("orion down")
        return {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}

    monkeypatch.setattr(bridge, "installed_tenants", fake_installed)
    monkeypatch.setattr(bridge, "run_bridge_for_tenant", fake_run)
    await bridge._run_once()
    assert seen == ["tenant-a", "tenant-b"]
