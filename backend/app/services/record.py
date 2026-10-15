"""Recording a sowing or a harvest that already happened, from the UI.

The platform decides which crop a field operation belongs to (SDK
``crop_cycles``: a sowing goes to the planned crop whose window holds its date,
a harvest to the crop it ends). An operation that lands on no crop is stored
but shows nowhere, so a record that would land on none is refused here with a
reason the user can act on (owner decision 2026-10-15), and nothing is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from nkz_platform_sdk.crop_cycles import resolve_crop_cycles

RECORDABLE = ("sowing", "harvesting")
_PROBE_ID = "urn:ngsi-ld:AgriParcelOperation:record-probe"
_FACTS = ("actual", "declared")


@dataclass(frozen=True)
class Match:
    ok: bool
    reason: str | None = None
    crop_id: str | None = None
    species: str | None = None
    variety: str | None = None
    role: str | None = None
    campaign: int | None = None


def _value(attr):
    if isinstance(attr, dict):
        return attr.get("@value", attr.get("value", attr.get("object")))
    return attr


def match_record(parcel_urn: str, crops: list[dict], ops: list[dict], op_type: str,
                 day: date, today: date) -> Match:
    """The crop a completed ``op_type`` on ``day`` would land on, or why it would land on none."""
    if op_type not in RECORDABLE:
        return Match(False, "unsupported_type")
    if day > today:
        return Match(False, "future_date")
    sowing = op_type == "sowing"
    at = max(today, day)
    before = resolve_crop_cycles(parcel_urn, crops, ops, at)
    probe = {"id": _PROBE_ID, "hasAgriParcel": parcel_urn, "operationType": op_type,
             "status": "completed", "endedAt": day.isoformat()}
    after = resolve_crop_cycles(parcel_urn, crops, [*ops, probe], at)
    if any(u.get("id") == _PROBE_ID for u in after.unassigned):
        return Match(False, "no_planned_crop" if sowing else "no_crop_to_close")

    side = "start" if sowing else "end"
    previous = {cy.crop_id: cy for cy in before.cycles}
    landed = [cy for cy in after.cycles
              if cy.crop_id in previous and getattr(cy, side) != getattr(previous[cy.crop_id], side)]
    if not landed:
        # Assigned, yet no boundary moved: an earlier record of the same kind already sets it.
        return Match(False, "already_recorded")
    cycle, old = landed[0], previous[landed[0].crop_id]
    if getattr(old, side).provenance == "actual":
        return Match(False, "already_recorded")
    if not sowing and cycle.start.provenance not in _FACTS:
        return Match(False, "not_sown")
    if not sowing and cycle.lifecycle == "perennial":
        # For the platform a harvest ends the crop; a vineyard or orchard lives on after it.
        return Match(False, "perennial_harvest_unsupported")
    crop = next((c for c in crops if c.get("id") == cycle.crop_id), {})
    return Match(True, crop_id=cycle.crop_id, species=cycle.species, variety=_value(crop.get("variety")),
                 role=cycle.role, campaign=cycle.campaign_label)
