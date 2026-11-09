"""Recently used spraying products / fertilisers of a holding, for suggestion chips."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import orion_ops

KINDS = ("spraying", "fertilization")
WINDOW_DAYS = 730  # 24 months
CACHE_TTL_S = 60.0
_CACHE: dict[tuple[str, str], tuple[float, list[dict]]] = {}


def _now() -> float:
    return time.monotonic()


def _val(v: Any) -> Any:
    """Unwrap a keyValues value that may arrive as {"value": ..} / {"@value": ..}."""
    while isinstance(v, dict):
        if "value" in v:
            v = v["value"]
        elif "@value" in v:
            v = v["@value"]
        else:
            return None
    return v


def _num(v: Any) -> float | int | None:
    v = _val(v)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


def _text(v: Any) -> str | None:
    v = _val(v)
    return v if isinstance(v, str) and v.strip() else None


def _day(op: dict) -> str | None:
    raw = _text(op.get("endedAt")) or _text(op.get("startedAt"))
    return raw[:10] if raw and len(raw) >= 10 else None


def _row(kind: str, op: dict) -> dict | None:
    day = _day(op)
    if kind == "spraying":
        name, rate, unit = _text(op.get("productName")), _num(op.get("productRate")), _text(op.get("productRateUnit"))
    else:
        name = _text(op.get("fertilizerType"))
        rate, unit = _num(op.get("fertilizerRateInput")), _text(op.get("fertilizerRateUnit"))
        if rate is None:
            rate = _num(op.get("fertilizerRate"))
            unit = "kg/ha" if rate is not None else None
    if not name or not day:
        return None
    return {"name": " ".join(name.split()), "lastRate": rate,
            "lastUnit": unit, "lastUsed": day}


def _group(kind: str, ops: list[dict]) -> list[dict]:
    rows = [r for r in (_row(kind, o) for o in ops) if r]
    rows.sort(key=lambda r: r["lastUsed"], reverse=True)  # stable: newest spelling wins
    seen: dict[str, dict] = {}
    for r in rows:
        seen.setdefault(r["name"].lower(), r)
    return list(seen.values())


def recent_products(tenant_id: str, kind: str, limit: int) -> list[dict]:
    """Raises RuntimeError when Orion fails. ``limit`` is applied after the cache."""
    key = (tenant_id, kind)
    hit = _CACHE.get(key)
    if hit and _now() - hit[0] < CACHE_TTL_S:
        return hit[1][:limit]
    since = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).isoformat()
    grouped = _group(kind, orion_ops.query_completed_operations_since(tenant_id, kind, since))
    _CACHE[key] = (_now(), grouped)
    return grouped[:limit]
