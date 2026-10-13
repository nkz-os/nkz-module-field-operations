"""Signed nutrient-plan summary from the FaST module (spec §5.3, RD 1051/2022 art. 5.1.a).

FAST_API_URL is FaST's in-cluster base URL including its API prefix; empty means FaST is not
installed in this deployment and the notebook shows no plan summaries."""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)
TIMEOUT_S = 10.0


async def plan_summary(tenant_id: str, parcel_id: str, campaign: int, *,
                       transport: httpx.AsyncBaseTransport | None = None) -> dict:
    base = os.getenv("FAST_API_URL", "").rstrip("/")
    secret = os.getenv("INTERNAL_SERVICE_SECRET", "")
    if not base:
        return {"status": "not_configured"}
    if not secret:
        logger.warning("plan summary: INTERNAL_SERVICE_SECRET not configured")
        return {"status": "unavailable"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport) as client:
            resp = await client.get(
                f"{base}/internal/plans/summary",
                params={"tenant_id": tenant_id, "parcel_id": parcel_id, "campaign": campaign},
                headers={"X-Internal-Service-Secret": secret})
    except httpx.HTTPError as exc:
        logger.warning("plan summary: FaST unreachable (%s) tenant=%s", type(exc).__name__,
                       tenant_id)
        return {"status": "unavailable"}
    if resp.status_code == 404:
        return {"status": "no_plan"}
    if resp.status_code != 200:
        logger.warning("plan summary: FaST answered %s tenant=%s", resp.status_code, tenant_id)
        return {"status": "unavailable"}
    return {"status": "ok", "summary": resp.json()}
