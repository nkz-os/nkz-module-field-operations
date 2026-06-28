"""Spraying pesticide authorization via BioOrchestrator reference API."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from ..config import BIOORCHESTRATOR_API_URL
from ..orion_ops import get_entity

logger = logging.getLogger(__name__)

_EPPO_RE = re.compile(r"^[A-Z]{4,6}$")


@dataclass
class PesticideValidationResult:
    status: str  # authorized | not_authorized | unknown_substance | skipped
    detail: str
    crop_eppo: Optional[str] = None
    product_name: Optional[str] = None


def _extract_relationship(entity: dict, rel_name: str) -> Optional[str]:
    rel = entity.get(rel_name) or entity.get(f"https://saref.etsi.org/saref4agri/{rel_name}")
    if isinstance(rel, dict):
        return rel.get("object")
    return None


def _extract_prop_value(prop: Any) -> Optional[str]:
    if prop is None:
        return None
    if isinstance(prop, dict):
        val = prop.get("value")
        if isinstance(val, dict) and "@value" in val:
            return str(val["@value"])
        if val is not None:
            return str(val)
        return None
    return str(prop)


def resolve_parcel_crop_eppo(tenant_id: str, parcel_id: str) -> Optional[str]:
    """Read AgriParcel.hasAgriCrop → AgriCrop.species (EPPO)."""
    parcel = get_entity(tenant_id, parcel_id)
    if not parcel:
        return None

    crop_uri = (
        _extract_relationship(parcel, "hasAgriCrop")
        or _extract_relationship(parcel, "refAgriCrop")
    )
    if not crop_uri:
        return None

    crop_entity = get_entity(tenant_id, crop_uri)
    if crop_entity:
        for key in ("species", "cropEppo", "eppoCode", "eppo"):
            val = _extract_prop_value(crop_entity.get(key))
            if val and _EPPO_RE.match(val.upper()):
                return val.upper()

    # Catalog-style URN: urn:ngsi-ld:AgriCrop:TRZAX
    tail = crop_uri.rsplit(":", 1)[-1]
    if _EPPO_RE.match(tail.upper()):
        return tail.upper()

    return None


def _substance_names(substances: list[dict]) -> set[str]:
    names: set[str] = set()
    for item in substances:
        if not isinstance(item, dict):
            continue
        for key in ("name", "product_name", "productName", "active_substance", "substance", "crop"):
            val = item.get(key)
            if val:
                names.add(str(val).strip().lower())
    return names


def _matches_product(product_name: str, authorized: set[str]) -> bool:
    needle = product_name.strip().lower()
    if not needle or not authorized:
        return False
    if needle in authorized:
        return True
    return any(needle in name or name in needle for name in authorized if len(name) >= 3)


def fetch_authorized_substances(
    crop_eppo: str,
    tenant_id: str,
    user_id: str = "",
) -> tuple[list[dict], Optional[str]]:
    """Call BioOrchestrator /api/graph/pesticides for crop EPPO."""
    url = f"{BIOORCHESTRATOR_API_URL.rstrip('/')}/api/graph/pesticides"
    headers = {"X-Tenant-ID": tenant_id}
    if user_id:
        headers["X-User-ID"] = user_id

    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(url, params={"crop": crop_eppo}, headers=headers)
            if resp.status_code != 200:
                return [], f"BioOrchestrator pesticides API returned {resp.status_code}"
            data = resp.json()
            return data.get("substances") or [], None
    except httpx.HTTPError as exc:
        return [], f"BioOrchestrator unreachable: {exc}"


def validate_spraying_product(
    tenant_id: str,
    parcel_id: str,
    product_name: str,
    user_id: str = "",
) -> PesticideValidationResult:
    """Validate productName against EU pesticides catalog for parcel crop."""
    product = (product_name or "").strip()
    if not product:
        return PesticideValidationResult(
            status="skipped",
            detail="No product name provided",
            product_name=product,
        )

    crop_eppo = resolve_parcel_crop_eppo(tenant_id, parcel_id)
    if not crop_eppo:
        logger.warning(
            "Pesticide validation skipped: no crop on parcel %s (tenant=%s)",
            parcel_id, tenant_id,
        )
        return PesticideValidationResult(
            status="skipped",
            detail="Parcel has no assigned crop — validation skipped",
            product_name=product,
        )

    substances, err = fetch_authorized_substances(crop_eppo, tenant_id, user_id)
    if err:
        logger.warning("Pesticide validation fail-open: %s", err)
        return PesticideValidationResult(
            status="unknown_substance",
            detail=err,
            crop_eppo=crop_eppo,
            product_name=product,
        )

    if not substances:
        return PesticideValidationResult(
            status="unknown_substance",
            detail=f"No catalog entries for crop {crop_eppo}",
            crop_eppo=crop_eppo,
            product_name=product,
        )

    authorized = _substance_names(substances)
    if _matches_product(product, authorized):
        return PesticideValidationResult(
            status="authorized",
            detail=f"Product authorized for crop {crop_eppo}",
            crop_eppo=crop_eppo,
            product_name=product,
        )

    return PesticideValidationResult(
        status="not_authorized",
        detail=f"'{product}' is not authorized for crop {crop_eppo}",
        crop_eppo=crop_eppo,
        product_name=product,
    )


def enforce_spraying_validation(
    tenant_id: str,
    parcel_id: str,
    operation_type: str,
    body: dict,
    user_id: str = "",
) -> Optional[PesticideValidationResult]:
    """Return validation result; raises ValueError with code for 422 on reject."""
    if operation_type != "spraying":
        return None

    product_name = body.get("productName") or body.get("product_name")
    if not product_name:
        return None

    result = validate_spraying_product(tenant_id, parcel_id, str(product_name), user_id)
    if result.status == "not_authorized":
        raise ValueError(result.detail)
    return result
