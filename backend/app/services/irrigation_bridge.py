"""Daily bridge: water meter counters -> completed irrigation operations.

Once an hour, per installed tenant, every Device that measures ``waterConsumption`` (a cumulative
counter in litres) is read for the last closed UTC days. The water of each day is summed per
owner parcel (a subparcel is an ordinary parcel here) and written as one completed
``AgriParcelOperation`` per parcel and day, with a deterministic id so a re-run updates instead of
duplicating. An operation a person cancelled or corrected is never changed again.

Unknown is never turned into a number: a counter reset, a missing boundary reading or an
unreadable series makes that day unknown, and nothing is written for it."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx
from nkz_platform_sdk.installations import InstalledTenantsUnavailable, installed_tenants
from nkz_platform_sdk.orion import OrionClient

from .. import config
from ..config import MODULE_ID
from .timeseries import fetch_counter_readings

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 3600
WINDOW_DAYS = 7  # closed UTC days re-stepped on every run (crop-health re-steps the same window)
ATTRIBUTE = "waterConsumption"
SOURCE = "sensor"
PARCEL_PREFIX = "urn:ngsi-ld:AgriParcel:"
_PAGE = 500


def _orion(tenant_id: str) -> OrionClient:
    return OrionClient(tenant_id, base_url=config.ORION_URL, context_url=config.CONTEXT_URL)


async def _merge_patch(client: OrionClient, entity_id: str, attrs: dict) -> None:
    """Merge-patch (creates missing attributes), as orion_ops.update_entity_attrs does."""
    resp = await client._client.patch(
        client._url(f"/ngsi-ld/v1/entities/{entity_id}"),
        json=attrs,
        headers=client._headers("application/json"),
    )
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"Orion-LD patch failed ({resp.status_code}): {resp.text}")


# --- pure helpers --------------------------------------------------------------------------

def closed_days(today: date) -> list[date]:
    return [today - timedelta(days=n) for n in range(WINDOW_DAYS, 0, -1)]


def daily_volumes(readings: list[tuple[datetime, float]], days: list[date]) -> dict[date, float]:
    """Litres per UTC day from a cumulative counter.

    Day D = last reading of D - last reading of D-1. No reading on D or on D-1, or a negative
    delta (meter reset or replaced), leaves D out: that day is unknown."""
    last_of_day: dict[date, float] = {}
    for ts, value in sorted(readings, key=lambda r: r[0]):
        last_of_day[ts.astimezone(timezone.utc).date()] = value
    out: dict[date, float] = {}
    for day in days:
        end = last_of_day.get(day)
        before = last_of_day.get(day - timedelta(days=1))
        if end is None or before is None:
            continue
        delta = end - before
        if delta < 0:
            continue
        out[day] = delta
    return out


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _plain(value: Any) -> Any:
    """keyValues or normalized attribute -> plain value. Unwraps one NGSI-LD attribute level
    ({"type", "value"} / {"type", "object"}) and a DateTime {"@value": ...}; any other dict
    (a modificationLog entry) is returned as is."""
    if isinstance(value, dict):
        if "@value" in value:
            return value["@value"]
        if "type" in value and "value" in value:
            inner = value["value"]
            return inner["@value"] if isinstance(inner, dict) and "@value" in inner else inner
        if "type" in value and "object" in value:
            return value["object"]
    return value


def owner_parcel(device: dict) -> str | None:
    """First AgriParcel in controlledAsset, else hasAgriParcel / refAgriParcel."""
    for asset in _as_list(_plain(device.get("controlledAsset"))):
        if isinstance(asset, str) and asset.startswith(PARCEL_PREFIX):
            return asset
    for name in ("hasAgriParcel", "refAgriParcel"):
        ref = _plain(device.get(name))
        if isinstance(ref, str) and ref.startswith(PARCEL_PREFIX):
            return ref
    return None


def measures_water(device: dict) -> bool:
    return ATTRIBUTE in _as_list(_plain(device.get("controlledProperty")))


def operation_id(tenant_id: str, parcel_urn: str, day: date) -> str:
    short = parcel_urn.rsplit(":", 1)[-1]
    return f"urn:ngsi-ld:AgriParcelOperation:{tenant_id}:irrigation-sensor-{short}-{day:%Y%m%d}"


def _dose(litres: float, area_ha: float) -> tuple[float, int]:
    """(waterVolume in m3 to the litre, waterPerHectare in L/ha to the litre)."""
    return round(litres / 1000.0, 3), int(round(litres / area_ha))


def is_protected(op: dict) -> bool:
    """A person decided on this operation: cancelled, or a log entry not written by the bridge."""
    if _plain(op.get("status")) == "cancelled":
        return True
    if _plain(op.get("dataSource")) not in (None, SOURCE):
        return True
    for entry in _as_list(_plain(op.get("modificationLog"))):
        if not isinstance(entry, dict) or entry.get("by") != SOURCE:
            return True
    return False


def _number(value: Any) -> float | None:
    v = _plain(value)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# --- Orion reads ---------------------------------------------------------------------------

async def _list_devices(client: OrionClient) -> list[dict]:
    devices, offset = [], 0
    while True:
        page = await client.query_entities(type="Device", limit=_PAGE, offset=offset, options="keyValues")
        devices.extend(page or [])
        if not page or len(page) < _PAGE:
            return devices
        offset += _PAGE


async def _get_or_none(client: OrionClient, entity_id: str, options: str | None = None) -> dict | None:
    try:
        return await client.get_entity(entity_id, options=options)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise


# --- bridge --------------------------------------------------------------------------------

def _new_operation(client: OrionClient, op_id: str, parcel_urn: str, day: date,
                   volume_m3: float, per_ha: int, devices: list[str]) -> dict:
    stamp = f"{day.isoformat()}T12:00:00Z"  # field-ops convention: the day is the fact
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": op_id,
        "type": "AgriParcelOperation",
        "@context": [client.context_url],
        "hasAgriParcel": {"type": "Relationship", "object": parcel_urn},
        "operationType": {"type": "Property", "value": "irrigation"},
        "workOrder": {"type": "Property", "value": f"SENSOR-{day.isoformat()}"},
        "status": {"type": "Property", "value": "completed"},
        "operator": {"type": "Property", "value": SOURCE},
        "dataSource": {"type": "Property", "value": SOURCE},
        "dateCreated": {"type": "Property", "value": {"@type": "DateTime", "@value": now}},
        "startedAt": {"type": "Property", "value": {"@type": "DateTime", "@value": stamp}},
        "endedAt": {"type": "Property", "value": {"@type": "DateTime", "@value": stamp}},
        "waterVolume": {"type": "Property", "value": volume_m3, "unitCode": "MTQ"},
        "waterPerHectare": {"type": "Property", "value": per_ha},
        "observedBy": {"type": "Relationship", "object": devices},
        "modificationLog": {"type": "Property", "value": []},
    }


async def run_bridge_for_tenant(tenant_id: str, today: date) -> dict:
    """One pass for a tenant over the last closed days. Returns write counts.

    ``skipped`` counts devices without an owner or readable series, and parcel-days left
    unwritten (no area, zero dose, a meter of the parcel unknown that day, a person's decision
    or a failed write)."""
    counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    days = closed_days(today)
    client = _orion(tenant_id)
    try:
        meters = [d for d in await _list_devices(client) if d.get("id") and measures_water(d)]
        # parcel -> device -> {day: litres}; an unknown day is absent
        by_parcel: dict[str, dict[str, dict[date, float]]] = {}
        for device in meters:
            device_urn = device["id"]
            parcel_urn = owner_parcel(device)
            if not parcel_urn:
                logger.warning("irrigation bridge: meter without parcel owner tenant=%s device=%s",
                               tenant_id, device_urn)
                counts["skipped"] += 1
                continue
            readings = await _device_readings(tenant_id, device_urn, days)
            if readings is None:
                counts["skipped"] += 1
                by_parcel.setdefault(parcel_urn, {})[device_urn] = {}
                continue
            volumes = daily_volumes(readings, days)
            for day in days:
                if day not in volumes:
                    logger.info("irrigation bridge: day unknown tenant=%s parcel=%s device=%s day=%s",
                                tenant_id, parcel_urn, device_urn, day)
            by_parcel.setdefault(parcel_urn, {})[device_urn] = volumes

        for parcel_urn, per_device in sorted(by_parcel.items()):
            await _bridge_parcel(client, tenant_id, parcel_urn, per_device, days, counts)
    finally:
        await client.close()
    logger.info("irrigation bridge: tenant=%s created=%d updated=%d unchanged=%d skipped=%d",
                tenant_id, counts["created"], counts["updated"], counts["unchanged"], counts["skipped"])
    return counts


async def _device_readings(tenant_id: str, device_urn: str,
                           days: list[date]) -> list[tuple[datetime, float]] | None:
    """Counter readings of the window plus the day before it, read one UTC day per request
    (the reader's row limit would cut a longer range). A day the reader could not give, or
    gave cut, contributes no readings, so it and the day after it come out unknown.
    None when no day could be read at all."""
    readings: list[tuple[datetime, float]] = []
    read_any = False
    for day in [days[0] - timedelta(days=1), *days]:
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        part = await fetch_counter_readings(tenant_id, device_urn, start, start + timedelta(days=1))
        if part is None:
            logger.warning("irrigation bridge: readings unknown tenant=%s device=%s day=%s",
                           tenant_id, device_urn, day)
            continue
        read_any = True
        readings.extend(part)
    return readings if read_any else None


async def _warn_if_operation_exists(client: OrionClient, tenant_id: str, parcel_urn: str,
                                    day: date, why: str) -> None:
    """The day now reads as no irrigation but an operation exists: leave it, tell someone."""
    op_id = operation_id(tenant_id, parcel_urn, day)
    try:
        existing = await _get_or_none(client, op_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("irrigation bridge: read failed tenant=%s parcel=%s op=%s: %s",
                     tenant_id, parcel_urn, op_id, exc)
        return
    if existing is not None:
        logger.warning("irrigation bridge: %s but operation exists, left unchanged tenant=%s parcel=%s day=%s op=%s",
                       why, tenant_id, parcel_urn, day, op_id)


async def _bridge_parcel(client: OrionClient, tenant_id: str, parcel_urn: str,
                         per_device: dict[str, dict[date, float]], days: list[date],
                         counts: dict) -> None:
    devices = sorted(per_device)
    totals: dict[date, float] = {}
    zero_days: list[date] = []
    for day in days:
        known = [v.get(day) for v in per_device.values()]
        if all(k is None for k in known):
            continue  # no meter of this parcel knows the day: nothing to say
        if any(k is None for k in known):
            # ASSUMPTION: a partial sum would be written as the day's total; skip until every
            # meter of the parcel is known (late telemetry inside the window fills it in).
            logger.warning("irrigation bridge: a meter is unknown, day skipped tenant=%s parcel=%s day=%s",
                           tenant_id, parcel_urn, day)
            counts["skipped"] += 1
            continue
        total = sum(known)
        if total > 0:
            totals[day] = total
        else:
            zero_days.append(day)
    for day in zero_days:
        await _warn_if_operation_exists(client, tenant_id, parcel_urn, day, "total is 0")
    if not totals:
        return

    parcel = await _get_or_none(client, parcel_urn, options="keyValues")
    area = _number(parcel.get("area")) if parcel else None
    if not area or area <= 0:
        logger.warning("irrigation bridge: parcel without positive area tenant=%s parcel=%s days=%d",
                       tenant_id, parcel_urn, len(totals))
        counts["skipped"] += len(totals)
        return

    for day, litres in sorted(totals.items()):
        volume_m3, per_ha = _dose(litres, area)
        op_id = operation_id(tenant_id, parcel_urn, day)
        if per_ha <= 0:
            logger.info("irrigation bridge: dose rounds to 0 L/ha, skipped tenant=%s parcel=%s day=%s",
                        tenant_id, parcel_urn, day)
            await _warn_if_operation_exists(client, tenant_id, parcel_urn, day, "dose rounds to 0")
            counts["skipped"] += 1
            continue
        try:
            existing = await _get_or_none(client, op_id)
            if existing is None:
                try:
                    await client.create_entity(
                        _new_operation(client, op_id, parcel_urn, day, volume_m3, per_ha, devices))
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 409:
                        raise
                    # Another replica created it between our read and write.
                    counts["unchanged"] += 1
                    logger.info("irrigation bridge: already created tenant=%s parcel=%s op=%s",
                                tenant_id, parcel_urn, op_id)
                    continue
                counts["created"] += 1
                logger.info("irrigation bridge: created tenant=%s parcel=%s op=%s litres=%.0f",
                            tenant_id, parcel_urn, op_id, litres)
                continue
            if is_protected(existing):
                counts["skipped"] += 1
                logger.info("irrigation bridge: person's decision kept tenant=%s parcel=%s op=%s",
                            tenant_id, parcel_urn, op_id)
                continue
            old_m3 = _number(existing.get("waterVolume"))
            old_ha = _number(existing.get("waterPerHectare"))
            if (old_m3 is not None and old_ha is not None
                    and round(old_m3 * 1000) == round(volume_m3 * 1000) and round(old_ha) == per_ha):
                counts["unchanged"] += 1
                continue
            # Re-read right before writing: a person may have decided since the first read.
            latest = await _get_or_none(client, op_id)
            if latest is None or is_protected(latest):
                counts["skipped"] += 1
                logger.info("irrigation bridge: person's decision kept (re-read) tenant=%s parcel=%s op=%s",
                            tenant_id, parcel_urn, op_id)
                continue
            log = list(_as_list(_plain(latest.get("modificationLog"))))
            log.append({"field": "waterVolume", "old": old_m3, "new": volume_m3, "by": SOURCE,
                        "at": datetime.now(timezone.utc).isoformat(), "method": "telemetry"})
            await _merge_patch(client, op_id, {
                "waterVolume": {"type": "Property", "value": volume_m3, "unitCode": "MTQ"},
                "waterPerHectare": {"type": "Property", "value": per_ha},
                "observedBy": {"type": "Relationship", "object": devices},
                "modificationLog": {"type": "Property", "value": log},
            })
            counts["updated"] += 1
            logger.info("irrigation bridge: updated tenant=%s parcel=%s op=%s m3 %s -> %s",
                        tenant_id, parcel_urn, op_id, old_m3, volume_m3)
        except Exception as exc:  # noqa: BLE001 — one failed write never stops the other days
            counts["skipped"] += 1
            logger.error("irrigation bridge: write failed tenant=%s parcel=%s op=%s: %s",
                         tenant_id, parcel_urn, op_id, exc)


async def _run_once() -> None:
    try:
        installs = await installed_tenants(MODULE_ID)
    except InstalledTenantsUnavailable as exc:
        logger.warning("irrigation bridge skipped: installed tenants unavailable: %s", exc)
        return
    today = datetime.now(timezone.utc).date()
    for tenant_id in installs.enabled:
        try:
            await run_bridge_for_tenant(tenant_id, today)
        except Exception as exc:  # noqa: BLE001 — one tenant never stops the others
            logger.error("irrigation bridge failed tenant=%s: %s", tenant_id, exc)


async def irrigation_bridge_loop() -> None:
    """Background loop: hourly bridge pass over every enabled tenant. Never raises."""
    logger.info("Irrigation bridge started (window=%dd, poll=%ds)", WINDOW_DAYS, POLL_INTERVAL_SECONDS)
    while True:
        try:
            await _run_once()
        except Exception as exc:  # noqa: BLE001
            logger.error("Error in irrigation bridge: %s", exc)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
