"""Service for handling external work orders (Odoo, API, mobile)."""
import logging
from typing import Optional

from ..orion_ops import create_operation, update_entity_attrs
from ..config import VALID_SOURCES

logger = logging.getLogger(__name__)


def create_external_work_order(
    tenant_id: str,
    parcel_id: str,
    operation_type: str,
    work_order: str,
    operator: str,
    source: str = "api",
    external_ref: Optional[str] = None,
    planned_date: Optional[str] = None,
    assigned_to: Optional[str] = None,
    **extra,
) -> dict:
    """Create an AgriParcelOperation from an external work order source.

    Sets status='issued' for external sources (odoo, api) so the field manager
    can review and accept before the operator starts working.
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"Invalid source '{source}'. Valid: {VALID_SOURCES}")

    entity = create_operation(
        tenant_id,
        parcel_id=parcel_id,
        operation_type=operation_type,
        work_order=work_order,
        operator=operator,
        data_source=source,
        source=source,
        external_ref=external_ref or work_order,
        planned_date=planned_date,
        assigned_to=assigned_to,
        **extra,
    )

    # Override status to 'issued' for external sources
    if source in ("odoo", "api"):
        operation_id = entity["id"]
        update_entity_attrs(tenant_id, operation_id, {
            "status": {"type": "Property", "value": "issued"}
        })
        entity["status"] = {"value": "issued"}

    logger.info(
        "Created external work order: source=%s ref=%s operation=%s",
        source, external_ref or work_order, entity.get("id"),
    )
    return entity
