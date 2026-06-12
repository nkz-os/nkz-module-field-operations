"""Admin Platform DB utilities — tenant discovery for background workers."""
from __future__ import annotations

import logging
from typing import Optional

import asyncpg

from .config import ADMIN_POSTGRES_URL

logger = logging.getLogger(__name__)


async def get_active_tenants() -> list[str]:
    """Return list of active tenant IDs from admin_platform.

    Returns empty list if ADMIN_POSTGRES_URL is not configured.
    """
    if not ADMIN_POSTGRES_URL:
        logger.warning(
            "ADMIN_POSTGRES_URL not set — cannot discover tenants. "
            "Stale operation check will skip tenant iteration."
        )
        return []

    conn: Optional[asyncpg.Connection] = None
    try:
        conn = await asyncpg.connect(ADMIN_POSTGRES_URL, timeout=5)
        rows = await conn.fetch(
            "SELECT tenant_id FROM admin_platform.tenants WHERE is_active = TRUE"
        )
        return [row["tenant_id"] for row in rows]
    except (asyncpg.PostgresError, ConnectionError, TimeoutError) as e:
        logger.error("Failed to query admin_platform.tenants: %s", e)
        return []
    finally:
        if conn:
            await conn.close()
