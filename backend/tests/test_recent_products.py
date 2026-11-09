"""GET /recent-products: the holding's recently used spraying products / fertilisers."""
import pytest
from fastapi.testclient import TestClient

from app import orion_ops
from app.main import app
from app.services import recent_products as svc

H = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u1"}
URL = "/api/field-operations/recent-products"


def spray(name, ended, rate=None, unit=None):
    e = {"id": f"urn:ngsi-ld:AgriParcelOperation:t:{name}{ended}", "type": "AgriParcelOperation",
         "productName": name, "endedAt": ended}
    if rate is not None:
        e["productRate"] = rate
    if unit:
        e["productRateUnit"] = unit
    return e


def fert(name, ended, **kw):
    return {"type": "AgriParcelOperation", "fertilizerType": name, "endedAt": ended, **kw}


@pytest.fixture
def env(monkeypatch):
    svc._CACHE.clear()
    state = {"calls": [], "ops": [], "fail": False}

    def fake(tenant, operation_type, since_iso, **kw):
        state["calls"].append((tenant, operation_type, since_iso))
        if state["fail"]:
            raise RuntimeError("orion down")
        return state["ops"]

    monkeypatch.setattr(orion_ops, "query_completed_operations_since", fake)
    return state


def get(**params):
    return TestClient(app).get(URL, headers=H, params=params)


def test_invalid_kind_is_400(env):
    for p in ({}, {"kind": "irrigation"}):
        r = get(**p)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_kind"
    assert env["calls"] == []


def test_needs_identity(env):
    assert TestClient(app).get(URL, params={"kind": "spraying"}).status_code == 401


def test_non_integer_limit_is_400(env):
    assert get(kind="spraying", limit="x").status_code == 400


def test_newest_first_with_rate_unit_and_date(env):
    env["ops"] = [spray("A", "2026-03-01T10:00:00Z", 1.5, "L/ha"),
                  spray("B", "2026-10-28T08:00:00+00:00", 2, "kg/ha"),
                  spray("C", "2026-05-02T08:00:00Z")]
    body = get(kind="spraying").json()
    assert body["kind"] == "spraying"
    assert body["products"] == [
        {"name": "B", "lastRate": 2, "lastUnit": "kg/ha", "lastUsed": "2026-10-28"},
        {"name": "C", "lastRate": None, "lastUnit": None, "lastUsed": "2026-05-02"},
        {"name": "A", "lastRate": 1.5, "lastUnit": "L/ha", "lastUsed": "2026-03-01"}]


def test_grouping_ignores_case_and_spaces_keeps_latest_spelling(env):
    env["ops"] = [spray("glifosato  36", "2026-01-01T00:00:00Z", 1, "L/ha"),
                  spray("Glifosato 36", "2026-06-01T00:00:00Z", 2, "L/ha"),
                  spray(" GLIFOSATO   36 ", "2026-03-01T00:00:00Z", 3, "L/ha")]
    [p] = get(kind="spraying").json()["products"]
    assert p == {"name": "Glifosato 36", "lastRate": 2, "lastUnit": "L/ha", "lastUsed": "2026-06-01"}


def test_wrapped_values_and_started_at_fallback(env):
    env["ops"] = [{"productName": {"value": "X"}, "productRate": {"@value": 3},
                   "productRateUnit": {"type": "Property", "value": "L/ha"},
                   "startedAt": {"@type": "DateTime", "@value": "2026-02-03T05:00:00Z"}}]
    [p] = get(kind="spraying").json()["products"]
    assert p == {"name": "X", "lastRate": 3, "lastUnit": "L/ha", "lastUsed": "2026-02-03"}


def test_entities_without_a_name_are_skipped(env):
    env["ops"] = [spray("", "2026-01-01T00:00:00Z"), {"endedAt": "2026-01-01T00:00:00Z"}]
    assert get(kind="spraying").json()["products"] == []


def test_fertilizer_prefers_what_the_user_typed(env):
    env["ops"] = [fert("Urea", "2026-09-01T00:00:00Z", fertilizerRate=300,
                       fertilizerRateInput=2, fertilizerRateUnit="t/ha"),
                  fert("Nitrato", "2026-08-01T00:00:00Z", fertilizerRate=150)]
    body = get(kind="fertilization").json()
    assert body["products"] == [
        {"name": "Urea", "lastRate": 2, "lastUnit": "t/ha", "lastUsed": "2026-09-01"},
        {"name": "Nitrato", "lastRate": 150, "lastUnit": "kg/ha", "lastUsed": "2026-08-01"}]
    assert env["calls"][0][1] == "fertilization"


@pytest.mark.parametrize("raw,expected", [(None, 10), ("0", 1), ("-4", 1), ("3", 3), ("500", 50)])
def test_limit_is_clamped(env, raw, expected):
    env["ops"] = [spray(f"P{i:02d}", f"2026-01-{i + 1:02d}T00:00:00Z") for i in range(60)]
    params = {"kind": "spraying"}
    if raw is not None:
        params["limit"] = raw
    assert len(get(**params).json()["products"]) == expected


def test_cache_serves_second_call_and_limit_applies_after_it(env):
    env["ops"] = [spray("A", "2026-01-01T00:00:00Z"), spray("B", "2026-02-01T00:00:00Z")]
    assert len(get(kind="spraying", limit=1).json()["products"]) == 1
    assert len(get(kind="spraying", limit=5).json()["products"]) == 2
    assert len(env["calls"]) == 1


def test_cache_is_per_tenant_and_kind(env):
    env["ops"] = [spray("A", "2026-01-01T00:00:00Z")]
    get(kind="spraying")
    TestClient(app).get(URL, headers={**H, "X-Tenant-ID": "tenant-b"}, params={"kind": "spraying"})
    get(kind="fertilization")
    assert [c[:2] for c in env["calls"]] == [("tenant-a", "spraying"), ("tenant-b", "spraying"),
                                             ("tenant-a", "fertilization")]


def test_cache_expires_after_60_seconds(env, monkeypatch):
    env["ops"] = [spray("A", "2026-01-01T00:00:00Z")]
    now = [1000.0]
    monkeypatch.setattr(svc, "_now", lambda: now[0])
    get(kind="spraying")
    now[0] += 59
    get(kind="spraying")
    now[0] += 2
    get(kind="spraying")
    assert len(env["calls"]) == 2


def test_window_is_24_months(env):
    get(kind="spraying")
    since = env["calls"][0][2]
    from datetime import datetime, timedelta, timezone
    d = datetime.fromisoformat(since)
    assert abs((datetime.now(timezone.utc) - d) - timedelta(days=730)) < timedelta(days=2)


def test_orion_failure_is_503_and_not_cached(env):
    env["fail"] = True
    r = get(kind="spraying")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "store_unavailable"
    env["fail"] = False
    assert get(kind="spraying").status_code == 200


# --- orion_ops.query_completed_operations_since -------------------------------------------

class _Resp:
    status_code = 200

    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class _Session:
    def __init__(self, pages):
        self.pages, self.params = pages, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.params.append(params)
        return _Resp(self.pages(params["offset"]))


class _Client:
    timeout = 5

    def __init__(self, pages):
        self._session = _Session(pages)

    def _url(self, p):
        return "http://orion" + p

    def _headers(self, ct):
        return {}


def test_query_sends_exact_q_and_stops_at_short_page(monkeypatch):
    sizes = {0: 500, 500: 500, 1000: 3}
    client = _Client(lambda off: [{"i": off + k} for k in range(sizes[off])])
    monkeypatch.setattr(orion_ops, "_get_client", lambda t: client)
    out = orion_ops.query_completed_operations_since("t", "spraying", "2025-01-01T00:00:00+00:00")
    assert len(out) == 1003
    p = client._session.params
    assert [x["offset"] for x in p] == [0, 500, 1000] and all(x["limit"] == 500 for x in p)
    assert p[0]["type"] == "AgriParcelOperation" and p[0]["options"] == "keyValues"
    assert p[0]["q"] == ('operationType=="spraying";status=="completed";'
                         'endedAt[@value]>="2025-01-01T00:00:00+00:00"')


def test_query_is_capped_at_ten_pages(monkeypatch):
    client = _Client(lambda off: [{}] * 500)
    monkeypatch.setattr(orion_ops, "_get_client", lambda t: client)
    out = orion_ops.query_completed_operations_since("t", "spraying", "2025-01-01T00:00:00+00:00")
    assert len(client._session.params) == 10 and len(out) == 5000


def test_query_failure_raises(monkeypatch):
    client = _Client(lambda off: [])
    client._session.get = lambda *a, **k: type("R", (), {"status_code": 500, "text": "boom"})()
    monkeypatch.setattr(orion_ops, "_get_client", lambda t: client)
    with pytest.raises(RuntimeError):
        orion_ops.query_completed_operations_since("t", "spraying", "x")
