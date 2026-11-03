"""Declaring a past crop: campaign and species, no dates.

A farmer who cannot say when a crop was sown or harvested can still say what
grew in a given campaign. That is one shared truth (SDK ``crop_cycles``): an
``AgriCrop`` that is closed (``harvested``), carries ``nkz:declaredCampaign``
and has no dates counts as history for rotation and previous-crop N credit.

Invariants of the entity written here (consumers rely on each of them):

- ``status: harvested``: otherwise crop-health lists it as an undated plan to sow;
- no date attribute of any kind: carbon would count a synthetic date as real;
- never ``hasAgriCrop`` / ``lastPlantedAt`` on the parcel: it is not in the field;
- a campaign strictly before the current one: FaST would take an equal one as
  the crop being planned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

EPPO = re.compile(r"^[A-Z]{4,6}$")  # same shape the module accepts for a crop's EPPO code
MIN_CAMPAIGN = 1900
DECLARED_CAMPAIGN_ATTR = "nkz:declaredCampaign"


class DeclareError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def parse_species(raw) -> str:
    value = raw.strip().upper() if isinstance(raw, str) else ""
    # "fallow" fits the shape but is not a crop; barbecho is out of v1.
    if not EPPO.match(value) or value == "FALLOW":
        raise DeclareError(422, "unknown_species", "eppo must be an EPPO code")
    return value


def parse_campaign(raw, today: date) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise DeclareError(422, "invalid_campaign", "campaign must be an integer year")
    if raw < MIN_CAMPAIGN:
        raise DeclareError(422, "invalid_campaign", "campaign is not a plausible year")
    if raw >= today.year:
        raise DeclareError(422, "campaign_not_past", "campaign must be before the current campaign")
    return raw


def declared_crop_id(tenant_id: str, parcel_urn: str, campaign: int) -> str:
    return f"urn:ngsi-ld:AgriCrop:{tenant_id}:{parcel_urn.split(':')[-1]}:declared-{campaign}"


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
    """Id of a dated main-crop cycle already in ``campaign``: facts beat declarations."""
    for cy in cycles:
        if cy.crop_id == own_id or cy.role != "main_crop":
            continue
        if (cy.start.date or cy.end.date) and cy.campaign_label == campaign:
            return cy.crop_id
    return None


def list_declared(cycles) -> list[dict]:
    rows = [{"campaign": cy.declared_campaign, "eppo": cy.species, "crop_id": cy.crop_id}
            for cy in cycles if cy.declared_only and cy.status == "harvested" and cy.role == "main_crop"]
    return sorted(rows, key=lambda r: (r["campaign"], r["crop_id"]))
