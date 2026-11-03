"""Declaring a past crop: campaign and species, no dates.

A farmer who cannot say when a crop was sown or harvested can still say what
grew in a given campaign. That is one shared truth (SDK ``crop_cycles``): an
``AgriCrop`` that is closed (``harvested``), carries ``nkz:declaredCampaign``
and has no dates counts as history for rotation and previous-crop N credit.

Invariants of the entity written here (consumers rely on each of them):

- ``status: harvested``: otherwise crop-health lists it as an undated plan to sow;
- no date attribute of any kind: carbon would count a synthetic date as real;
- never ``hasAgriCrop`` / ``lastPlantedAt`` on the parcel: it is not in the field;
- a campaign already over: FaST would take the campaign being planned as its
  own previous crop. Over means the same rollover the planning screens use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

# Exact shape FaST reads a cycle species with; a code it would drop must not be written.
EPPO = re.compile(r"^[A-Z0-9]{5,6}$")
MIN_CAMPAIGN = 1900
# Matches the SDK (crop_cycles.DECLARED_ROLLOVER_MONTH) and the planning rollover:
# from this month the campaign of the current year counts as over.
ROLLOVER_MONTH = 7
_FACTS = ("actual", "declared")
PARCEL_PREFIX = "urn:ngsi-ld:AgriParcel:"
DECLARED_CAMPAIGN_ATTR = "nkz:declaredCampaign"


class DeclareError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def parse_species(raw) -> str:
    value = raw.strip().upper() if isinstance(raw, str) else ""
    # "fallow" fits the shape but is not a crop; barbecho is out of v1.
    if not EPPO.match(value) or value == "FALLOW":
        raise DeclareError(422, "invalid_species", "eppo must be an EPPO code (5-6 letters or digits)")
    return value


def parse_campaign(raw, today: date) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise DeclareError(422, "invalid_campaign", "campaign must be an integer year")
    if raw < MIN_CAMPAIGN:
        raise DeclareError(422, "invalid_campaign", "campaign is not a plausible year")
    if raw > today.year or (raw == today.year and today.month < ROLLOVER_MONTH):
        raise DeclareError(422, "campaign_not_past", "campaign must be before the current campaign")
    return raw


def declared_crop_id(tenant_id: str, parcel_urn: str, campaign: int) -> str:
    # The whole local part: it may contain ':' and two parcels must never share an id.
    local = parcel_urn.removeprefix(PARCEL_PREFIX)
    return f"urn:ngsi-ld:AgriCrop:{tenant_id}:{local}:declared-{campaign}"


def build_entity(tenant_id: str, parcel_urn: str, campaign: int, eppo: str) -> dict:
    return {
        "id": declared_crop_id(tenant_id, parcel_urn, campaign),
        "type": "AgriCrop",
        "hasAgriParcel": {"type": "Relationship", "object": parcel_urn},
        "cropRole": {"type": "Property", "value": "main_crop"},
        "status": {"type": "Property", "value": "harvested"},
        "species": {"type": "Property", "value": eppo},
        DECLARED_CAMPAIGN_ATTR: {"type": "Property", "value": campaign},
    }


def species_patch(eppo: str) -> dict:
    return {"species": {"type": "Property", "value": eppo}}


def dated_conflict(cycles, campaign: int, own_id: str) -> str | None:
    """Id of a main-crop cycle in ``campaign`` whose start or end is a fact: facts beat declarations.

    A plan that was never sown (dates only planned) is not a fact and does not block.
    A perennial blocks every campaign it is alive in, not only its planting year."""
    for cy in cycles:
        if cy.crop_id == own_id or cy.role != "main_crop":
            continue
        fact = ((cy.start.date and cy.start.provenance in _FACTS)
                or (cy.end.date and cy.end.provenance in _FACTS))
        if fact and cy.in_campaign(campaign):
            return cy.crop_id
    return None


def list_declared(cycles) -> list[dict]:
    rows = [{"campaign": cy.declared_campaign, "eppo": cy.species, "crop_id": cy.crop_id}
            for cy in cycles if cy.declared_only and cy.status == "harvested" and cy.role == "main_crop"]
    return sorted(rows, key=lambda r: (r["campaign"], r["crop_id"]))


def declared_only_id(cycles, crop_id: str) -> bool:
    """True only for a declared-only cycle: a dated or planned crop is never deletable here."""
    return any(cy.crop_id == crop_id and cy.declared_only for cy in cycles)
