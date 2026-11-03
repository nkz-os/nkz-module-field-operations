"""Declaring an existing perennial plantation (an olive grove planted in 2000).

The parcel exists but nobody ever sowed the stand through the platform. The
owner states species and planting year; that is one ``AgriCrop`` the SDK
(``crop_cycles``) reads as a perennial main crop whose start is declared
(``plantingDateSource: manual``), so harvests can be recorded against it.

Invariants of the entity built here:

- no ``harvestDate`` / ``expectedTerminationDate``: a stand has no planned end;
- ``plantingDate`` is the declared start, never a plan window;
- ``hasAgriCrop`` on the parcel is not written here: ``reconcile_parcel`` links it.
"""

from __future__ import annotations

from datetime import date

# Woody species (EPPO) accepted for a plantation. Copied from the BioOrchestrator
# species registry (woody: true) on purpose: no runtime call to another module.
WOODY_EPPO = frozenset({
    "VITVI", "OLVEU", "PRNDU", "PIAVE", "MABSD", "PYUCO", "PRNPS", "PRNAR", "PRNDO", "PRNAV",
})
MIN_YEAR = 1900
PARCEL_PREFIX = "urn:ngsi-ld:AgriParcel:"


class PlantationError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def plantation_crop_id(tenant_id: str, parcel_urn: str, planting_year: int) -> str:
    """``urn:ngsi-ld:AgriCrop:{tenant}:{local}:plantation-{year}``.

    ``{local}`` is the parcel URN without ``urn:ngsi-ld:AgriParcel:`` (it may hold
    ':', so the whole of it is kept and two parcels never share an id). When that
    local part already starts with ``{tenant}:`` the prefix is dropped so the
    tenant does not appear twice.
    """
    local = parcel_urn.removeprefix(PARCEL_PREFIX)
    local = local.removeprefix(f"{tenant_id}:")
    return f"urn:ngsi-ld:AgriCrop:{tenant_id}:{local}:plantation-{planting_year}"


def parse_species(raw) -> str:
    value = raw.strip().upper() if isinstance(raw, str) else ""
    if value not in WOODY_EPPO:
        raise PlantationError(422, "invalid_species", "eppo must be a woody species code")
    return value


def parse_planting(raw_year, raw_date, today: date) -> date:
    """The planting day: ``raw_date`` when given (its year must be ``raw_year``), else 1 January."""
    if isinstance(raw_year, bool) or not isinstance(raw_year, int) or raw_year < MIN_YEAR or raw_year > today.year:
        raise PlantationError(422, "invalid_year", f"planting_year must be an integer from {MIN_YEAR} to the current year")
    if raw_date in (None, ""):
        day = date(raw_year, 1, 1)
    else:
        try:
            day = date.fromisoformat(str(raw_date))
        except ValueError:
            raise PlantationError(422, "invalid_date", "planting_date must be YYYY-MM-DD")
        if day.year != raw_year:
            raise PlantationError(422, "invalid_date", "planting_date must fall in planting_year")
    if day > today:
        raise PlantationError(422, "future_date", "planting_date cannot be in the future")
    return day


def build_plantation(tenant_id: str, parcel_urn: str, eppo: str, planting: date, variety: str | None) -> dict:
    entity = {
        "id": plantation_crop_id(tenant_id, parcel_urn, planting.year),
        "type": "AgriCrop",
        "hasAgriParcel": {"type": "Relationship", "object": parcel_urn},
        "cropRole": {"type": "Property", "value": "main_crop"},
        "cropLifecycle": {"type": "Property", "value": "perennial"},
        "status": {"type": "Property", "value": "active"},
        "species": {"type": "Property", "value": eppo},
        "plantingDate": {"type": "Property", "value": {"@type": "Date", "@value": planting.isoformat()}},
        "plantingDateSource": {"type": "Property", "value": "manual"},
    }
    if variety:
        entity["variety"] = {"type": "Property", "value": variety}
    return entity
