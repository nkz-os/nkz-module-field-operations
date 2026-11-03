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

from nkz_platform_sdk.crop_cycles import UPROOTING, CropCycle, resolve_crop_cycles

RECORDABLE = ("sowing", "harvesting", "uprooting")
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
    harvest_campaign: str | None = None


def _value(attr):
    if isinstance(attr, dict):
        return attr.get("@value", attr.get("value", attr.get("object")))
    return attr


def _probe(op_type: str, day: date) -> dict:
    probe = {"id": _PROBE_ID, "operationType": op_type, "status": "completed", "endedAt": day.isoformat()}
    if op_type == "uprooting":
        # Uprooting is a record type, stored as a tillage the SDK reads as the end of a stand.
        probe.update(operationType="tillage", tillageType=UPROOTING)
    return probe


def _hit(cycle: CropCycle, crops: list[dict], harvest_campaign: str | None = None) -> Match:
    crop = next((c for c in crops if c.get("id") == cycle.crop_id), {})
    return Match(True, crop_id=cycle.crop_id, species=cycle.species, variety=_value(crop.get("variety")),
                 role=cycle.role, campaign=cycle.campaign_label, harvest_campaign=harvest_campaign)


def _match_uprooting(parcel_urn, crops, before, after, day: date) -> Match:
    stands = {cy.crop_id: cy for cy in before.cycles if cy.lifecycle == "perennial"}
    if any(cy.end.provenance == "actual" for cy in stands.values()) and not any(
            cy.end.provenance != "actual" and cy.start.provenance in _FACTS for cy in stands.values()):
        return Match(False, "already_closed")
    if not stands:
        return Match(False, "not_perennial" if before.cycles else "no_crop_to_close")
    landed = [cy for cy in after.cycles if cy.crop_id in stands and cy.end.provenance == "actual"
              and stands[cy.crop_id].end.provenance != "actual"]
    if not landed:
        return Match(False, "no_crop_to_close")
    cycle, old = landed[0], stands[landed[0].crop_id]
    if old.start.provenance not in _FACTS:
        return Match(False, "not_sown")
    if old.harvests and day.isoformat() < old.harvests[-1]["date"]:
        return Match(False, "date_before_last_harvest")
    return _hit(cycle, crops)


def match_record(parcel_urn: str, crops: list[dict], ops: list[dict], op_type: str,
                 day: date, today: date) -> Match:
    """The crop a completed ``op_type`` on ``day`` would land on, or why it would land on none."""
    if op_type not in RECORDABLE:
        return Match(False, "unsupported_type")
    if day > today:
        return Match(False, "future_date")
    sowing = op_type == "sowing"
    uprooting = op_type == "uprooting"
    at = max(today, day)
    before = resolve_crop_cycles(parcel_urn, crops, ops, at)
    probe = {**_probe(op_type, day), "hasAgriParcel": parcel_urn}
    after = resolve_crop_cycles(parcel_urn, crops, [*ops, probe], at)
    unassigned = any(u.get("id") == _PROBE_ID for u in after.unassigned)
    if uprooting:
        if unassigned:
            stands = [cy for cy in before.cycles if cy.lifecycle == "perennial"]
            if any(cy.end.provenance == "actual" for cy in stands):
                return Match(False, "already_closed")
            if stands and any(h["date"] > day.isoformat() for cy in stands for h in cy.harvests):
                return Match(False, "date_before_last_harvest")
            return Match(False, "not_perennial" if before.cycles and not stands else "no_crop_to_close")
        return _match_uprooting(parcel_urn, crops, before, after, day)
    if unassigned:
        return Match(False, "no_planned_crop" if sowing else "no_crop_to_close")

    if not sowing:
        # A perennial's harvest never moves a boundary: it shows up in the cycle's harvests.
        for cy in after.cycles:
            if cy.lifecycle == "perennial" and any(h["id"] == _PROBE_ID for h in cy.harvests):
                old = next((b for b in before.cycles if b.crop_id == cy.crop_id), None)
                if cy.start.provenance not in _FACTS:
                    return Match(False, "not_sown")
                if old and any(h["date"] == day.isoformat() for h in old.harvests):
                    return Match(False, "already_recorded")
                campaign = next((c for c in cy.harvest_campaigns
                                 if any(h["id"] == _PROBE_ID for h in c.harvests)), None)
                return _hit(cy, crops, campaign.display if campaign else None)

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
    return _hit(cycle, crops)
