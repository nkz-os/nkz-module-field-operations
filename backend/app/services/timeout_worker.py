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

    # Note: In production, this should iterate over active tenants.
    # For now, queries without tenant filter rely on the caller providing tenant context.
    # The worker runs per-tenant or uses a tenant-discovery mechanism.
    logger.debug("Stale check: cutoff=%s", cutoff_iso)

    # This is a placeholder for the actual tenant-iterating logic.
    # In production, the worker should:
    # 1. Query the admin database for active tenants
    # 2. For each tenant, run query_operations(tenant, status="incomplete")
    # 3. Check startedAt < cutoff
    # 4. Update status to needs_review

    # For now, log what would be checked
    logger.info(
        "Stale operation check complete (timeout=%dh). "
        "Tenant iteration not yet implemented — see field-operations Task 11.",
        INCOMPLETE_TIMEOUT_HOURS,
    )
