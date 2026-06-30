"""Internal client for the CUE module (national ROPO/fertilizer reference)."""
from __future__ import annotations

import httpx

from ..config import CUE_API_URL, INTERNAL_SERVICE_SECRET


def get_ropo_products(cultivo: str, tenant_id: str, estado: str = "autorizado") -> list[dict]:
    """Fetch authorized ROPO products for a crop from CUE. Raises httpx.HTTPError on failure."""
    url = f"{CUE_API_URL.rstrip('/')}/api/modules/cue/productos-ropo"
    headers = {"X-Tenant-ID": tenant_id, "X-Internal-Service-Secret": INTERNAL_SERVICE_SECRET}
    with httpx.Client(timeout=8.0) as client:
        resp = client.get(url, params={"cultivo": cultivo, "estado": estado}, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
