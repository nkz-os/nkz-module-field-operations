"""Recording a sowing or a harvest that already happened, from the UI.

The platform decides which crop a field operation belongs to (SDK
``crop_cycles``: a sowing goes to the planned crop whose window holds its date,
a harvest to the crop it ends). An operation that lands on no crop is stored
but shows nowhere, so a record that would land on none is refused here with a
reason the user can act on (owner decision 2026-10-15), and nothing is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from nkz_platform_sdk.crop_cycles import UPROOTING, CropCycle, resolve_crop_cycles

_MATCHED = ("sowing", "harvesting", "uprooting")  # land on a crop through its window
RECORDABLE = _MATCHED + ("irrigation", "fertilization", "spraying", "tillage", "haymaking", "baling", "scouting")
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
    harvest_campaign_label: int | None = None


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


def _hit(cycle: CropCycle, crops: list[dict], harvest_campaign=None) -> Match:
    crop = next((c for c in crops if c.get("id") == cycle.crop_id), {})
    # A stand's campaign_label is its planting year, not a season: only annual crops report it.
    campaign = None if cycle.lifecycle == "perennial" else cycle.campaign_label
    return Match(True, crop_id=cycle.crop_id, species=cycle.species, variety=_value(crop.get("variety")),
                 role=cycle.role, campaign=campaign,
                 harvest_campaign=harvest_campaign.display if harvest_campaign else None,
                 harvest_campaign_label=harvest_campaign.label if harvest_campaign else None)


def _match_uprooting(parcel_urn, crops, ops, before, day: date, at: date) -> Match:
    """One place decides every uprooting refusal, from the stand it would pull out."""
    stands = [cy for cy in before.cycles if cy.lifecycle == "perennial"]
    if not stands:
        return Match(False, "not_perennial" if before.cycles else "no_crop_to_close")
    # An open stand is the target (the latest planted); a closed one only when none is open.
    open_ = [cy for cy in stands if cy.end.provenance != "actual"]
    if not open_:
        return Match(False, "already_closed")
    alive = [cy for cy in open_ if cy.start.provenance in _FACTS]
    if not alive:
        return Match(False, "not_sown")
    target = max(alive, key=lambda cy: cy.start.date or date.min)
    if target.harvests and day.isoformat() < target.harvests[-1]["date"]:
        return Match(False, "date_before_last_harvest")
    probe = {**_probe("uprooting", day), "hasAgriParcel": parcel_urn, "hasAgriCrop": target.crop_id}
    after = resolve_crop_cycles(parcel_urn, crops, [*ops, probe], at)
    hit = next((cy for cy in after.cycles if cy.crop_id == target.crop_id), None)
    if any(u.get("id") == _PROBE_ID for u in after.unassigned) or hit is None \
            or hit.end.provenance != "actual":
        return Match(False, "no_crop_to_close")
    return _hit(hit, crops)


def match_record(parcel_urn: str, crops: list[dict], ops: list[dict], op_type: str,
                 day: date, today: date) -> Match:
    """The crop a completed ``op_type`` on ``day`` would land on, or why it would land on none."""
    if op_type not in _MATCHED:
        return Match(False, "unsupported_type")
    if day > today + timedelta(days=1):  # one day of margin, as for the other types
        return Match(False, "future_date")
    sowing = op_type == "sowing"
    uprooting = op_type == "uprooting"
    at = max(today, day)
    before = resolve_crop_cycles(parcel_urn, crops, ops, at)
    if uprooting:
        return _match_uprooting(parcel_urn, crops, ops, before, day, at)
    probe = {**_probe(op_type, day), "hasAgriParcel": parcel_urn}
    after = resolve_crop_cycles(parcel_urn, crops, [*ops, probe], at)
    unassigned = any(u.get("id") == _PROBE_ID for u in after.unassigned)
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
                return _hit(cy, crops, campaign)

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


def current_cycle(parcel_urn: str, crops: list[dict], ops: list[dict], day: date, today: date,
                  sown_only: bool = False, prefer_cover: bool = False) -> CropCycle | None:
    """The one crop standing on ``day``, preferring the main crop; None when none or several remain.

    ``sown_only`` keeps cycles whose start is a fact (sown or planted), not a plan."""
    timeline = resolve_crop_cycles(parcel_urn, crops, ops, max(today, day))
    standing = [cy for cy in timeline.cycles
                if cy.start.date and cy.start.date <= day and (cy.end.date is None or day <= cy.end.date)]
    if sown_only:
        standing = [cy for cy in standing if cy.start.provenance in _FACTS]
    if prefer_cover:  # the stand a terminating tillage will end
        covers = [cy for cy in standing if cy.role in ("cover_crop", "catch_crop")]
        if covers:
            standing = covers
    main = [cy for cy in standing if cy.role == "main_crop"]
    standing = main or standing
    return standing[0] if len(standing) == 1 else None


def resolve_current_crop(parcel_urn: str, crops: list[dict], ops: list[dict], day: date, today: date) -> str | None:
    """Crop id for ``hasAgriCrop`` of a fact on ``day``: only when exactly one candidate stands."""
    cycle = current_cycle(parcel_urn, crops, ops, day, today)
    return cycle.crop_id if cycle else None
