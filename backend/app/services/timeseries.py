"""Module-signed reads of device telemetry from timeseries-reader.

The reader's routes take the gateway signature: a module backend has no user token, so it
signs an empty token for the tenant (X-Auth-Signature over "|{tenant}|{ts}" with HMAC_SECRET)
and sends no Authorization header. Times go as ISO strings (epoch seconds give a 500)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx
from nkz_platform_sdk.crypto import generate_hmac_signature

logger = logging.getLogger(__name__)

TIMEOUT_S = 30.0
ATTRIBUTE = "waterConsumption"
# The reader cuts the series at `limit` rows, oldest first, so a full page may have lost the
# latest readings. A full page is treated as unknown rather than read as a smaller volume.
READ_LIMIT = 20000


def _base_url() -> str:
    return os.getenv("TIMESERIES_READER_URL", "http://timeseries-reader-service:5000").rstrip("/")


def _parse_ts(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    # The reader stores observed_at in UTC; a stamp without offset is UTC.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def fetch_counter_readings(
    tenant_id: str,
    device_urn: str,
    start: datetime,
    end: datetime,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[tuple[datetime, float]] | None:
    """Oldest-first (time, litres) readings of the meter counter in [start, end).

    None on any error (logged with tenant and device): the caller treats the days as unknown."""
    secret = os.getenv("HMAC_SECRET", "")
    if not secret:
        logger.error("timeseries: HMAC_SECRET not configured tenant=%s device=%s", tenant_id, device_urn)
        return None
    headers = {
        "X-Tenant-ID": tenant_id,
        "X-Auth-Signature": generate_hmac_signature(secret, "", tenant_id),
    }
    params = {
        "time_from": start.isoformat(),
        "time_to": end.isoformat(),
        "attrs": ATTRIBUTE,
        "limit": READ_LIMIT,
    }
    url = f"{_base_url()}/api/timeseries/v2/entities/{device_urn}/data"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport) as client:
            resp = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("timeseries: reader unreachable (%s) tenant=%s device=%s",
                       type(exc).__name__, tenant_id, device_urn)
        return None
    if resp.status_code != 200:
        logger.warning("timeseries: reader answered %s tenant=%s device=%s",
                       resp.status_code, tenant_id, device_urn)
        return None
    try:
        raw = resp.json()
        timestamps = raw.get("timestamps") or []
        values = (raw.get("attributes") or {}).get(ATTRIBUTE) or []
        if len(timestamps) >= READ_LIMIT:
            logger.warning("timeseries: page full (%d rows), readings may be cut tenant=%s device=%s",
                           len(timestamps), tenant_id, device_urn)
            return None
        readings: list[tuple[datetime, float]] = []
        for ts, value in zip(timestamps, values):
            if ts is None or value is None:
                continue
            readings.append((_parse_ts(ts), float(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        logger.warning("timeseries: unreadable answer (%s) tenant=%s device=%s",
                       exc, tenant_id, device_urn)
        return None
    readings.sort(key=lambda r: r[0])
    return readings
