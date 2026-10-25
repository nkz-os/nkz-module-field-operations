"""Module-signed reader client for meter counters."""
import re
from datetime import datetime, timezone

import httpx
import pytest

from app.services.timeseries import fetch_counter_readings

START = datetime(2026, 10, 1, tzinfo=timezone.utc)
END = datetime(2026, 10, 9, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_reader_signs_as_module(monkeypatch):
    monkeypatch.setenv("HMAC_SECRET", "test-secret")
    monkeypatch.setenv("TIMESERIES_READER_URL", "http://reader.test")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, json={
            "timestamps": ["2026-10-02T08:00:00Z", "2026-10-01T23:50:00Z"],
            "attributes": {"waterConsumption": [104000, 100000]},
        })

    rows = await fetch_counter_readings("tenant-a", "urn:ngsi-ld:Device:m-1", START, END,
                                        transport=httpx.MockTransport(handler))
    req = seen["request"]
    assert req.url.path == "/api/timeseries/v2/entities/urn:ngsi-ld:Device:m-1/data"
    assert req.headers["X-Tenant-ID"] == "tenant-a"
    assert re.fullmatch(r"[0-9a-f]{64}:\d+", req.headers["X-Auth-Signature"])
    assert "Authorization" not in req.headers
    assert req.url.params["time_from"] == START.isoformat()
    assert req.url.params["time_to"] == END.isoformat()
    assert req.url.params["attrs"] == "waterConsumption"
    assert rows == [(datetime(2026, 10, 1, 23, 50, tzinfo=timezone.utc), 100000.0),
                    (datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), 104000.0)]


@pytest.mark.asyncio
async def test_reader_error_returns_none(monkeypatch):
    monkeypatch.setenv("HMAC_SECRET", "test-secret")
    transport = httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))
    assert await fetch_counter_readings("tenant-a", "urn:ngsi-ld:Device:m-1", START, END,
                                        transport=transport) is None


@pytest.mark.asyncio
async def test_reader_without_secret_returns_none(monkeypatch):
    monkeypatch.delenv("HMAC_SECRET", raising=False)
    transport = httpx.MockTransport(lambda r: pytest.fail("must not call the reader unsigned"))
    assert await fetch_counter_readings("tenant-a", "urn:ngsi-ld:Device:m-1", START, END,
                                        transport=transport) is None
