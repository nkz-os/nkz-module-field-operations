"""Background worker to mark stale incomplete operations as needs_review."""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from ..config import INCOMPLETE_TIMEOUT_HOURS

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 3600  # check every hour


async def check_stale_operations():
    """Background loop: periodically find and flag stale operations."""
    logger.info(
        "Stale operation check started (timeout=%dh, poll=%ds)",
        INCOMPLETE_TIMEOUT_HOURS, POLL_INTERVAL_SECONDS,
    )
    while True:
        try:
            await _process_stale_operations()
        except Exception as e:
            logger.error("Error in stale operation check: %s", e)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def _process_stale_operations():
    """Query incomplete operations older than timeout and flag them."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=INCOMPLETE_TIMEOUT_HOURS)
    cutoff_iso = cutoff.isoformat()

    # Import here to avoid circular imports at module level
    from ..orion_ops import query_operations, update_entity_attrs
    from ..admin_db import get_active_tenants

    tenants = await get_active_tenants()
    if not tenants:
        logger.info(
            "No tenants discovered — stale check skipped. "
            "Set ADMIN_POSTGRES_URL to enable tenant iteration."
        )
        return

    logger.debug("Stale check: cutoff=%s, tenants=%d", cutoff_iso, len(tenants))

    for tenant_id in tenants:
        try:
            operations = query_operations(tenant_id, status="incomplete", limit=200)
        except Exception as e:
            logger.error("Failed to query operations for tenant %s: %s", tenant_id, e)
            continue

        flagged = 0
        for op in operations:
            started_at_str = None
            if isinstance(op.get("startedAt"), dict):
                val = op["startedAt"].get("value")
                if isinstance(val, dict):
                    started_at_str = val.get("@value")
                elif isinstance(val, str):
                    started_at_str = val

            if not started_at_str:
                continue

            try:
                started_at = datetime.fromisoformat(started_at_str)
            except (ValueError, TypeError):
                continue

            if started_at < cutoff:
                op_id = op.get("id", "")
                logger.info(
                    "Flagging stale operation %s (started=%s, cutoff=%s)",
                    op_id, started_at_str, cutoff_iso,
                )
                try:
                    update_entity_attrs(tenant_id, op_id, {
                        "status": {"type": "Property", "value": "needs_review"},
                    })
                    flagged += 1
                except Exception as e:
                    logger.error("Failed to flag operation %s: %s", op_id, e)

        logger.info(
            "Tenant %s: %d incomplete ops, %d flagged stale",
            tenant_id, len(operations), flagged,
        )
