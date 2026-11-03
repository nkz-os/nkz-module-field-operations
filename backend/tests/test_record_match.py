"""Which crop a recorded sowing or harvest lands on (SDK crop_cycles rule, owner decision A).

A record that would land on no crop is refused with a reason, never stored invisible.
"""
from datetime import date

from app.services.record import match_record

P = "urn:ngsi-ld:AgriParcel:p1"
TODAY = date(2026, 11, 20)
PLANNED = {"id": "urn:ngsi-ld:AgriCrop:t:p1:2027:1", "type": "AgriCrop", "refAgriParcel": P,
           "status": "planned", "cropRole": "main_crop", "species": "TRZAX", "variety": "KWS KEITUM",
           "sowingWindowStart": "2026-11-01", "expectedTerminationDate": "2027-07-31"}


def _op(kind, day, **kw):
    return {"id": f"urn:ngsi-ld:AgriParcelOperation:t:{kind}{day}", "hasAgriParcel": P,
            "operationType": kind, "status": "completed", "endedAt": day, **kw}


def test_sowing_in_the_planned_window_lands_on_the_planned_crop():
    m = match_record(P, [PLANNED], [], "sowing", date(2026, 11, 10), TODAY)
    assert m.ok and m.crop_id == PLANNED["id"]
    assert m.species == "TRZAX" and m.variety == "KWS KEITUM" and m.campaign == 2027


def test_sowing_without_any_plan_is_refused():
    m = match_record(P, [], [], "sowing", date(2026, 11, 10), TODAY)
    assert not m.ok and m.reason == "no_planned_crop"


def test_sowing_far_outside_the_window_is_refused():
    m = match_record(P, [PLANNED], [], "sowing", date(2026, 5, 1), TODAY)
    assert not m.ok and m.reason == "no_planned_crop"


def test_future_date_is_refused():
    m = match_record(P, [PLANNED], [], "sowing", date(2026, 11, 21), TODAY)
    assert not m.ok and m.reason == "future_date"


def test_second_sowing_of_the_same_crop_is_refused():
    m = match_record(P, [PLANNED], [_op("sowing", "2026-11-10")], "sowing", date(2026, 11, 5), TODAY)
    assert not m.ok and m.reason == "already_recorded"


def test_harvest_of_a_sown_crop_lands_on_it():
    m = match_record(P, [PLANNED], [_op("sowing", "2026-11-10")], "harvesting", date(2027, 7, 2),
                     date(2027, 7, 3))
    assert m.ok and m.crop_id == PLANNED["id"]


def test_harvest_of_a_crop_never_sown_is_refused():
    m = match_record(P, [PLANNED], [], "harvesting", date(2027, 7, 2), date(2027, 7, 3))
    assert not m.ok and m.reason == "not_sown"


def test_harvest_without_any_crop_is_refused():
    m = match_record(P, [], [], "harvesting", date(2027, 7, 2), date(2027, 7, 3))
    assert not m.ok and m.reason == "no_crop_to_close"


def test_harvest_already_recorded_is_refused():
    ops = [_op("sowing", "2026-11-10"), _op("harvesting", "2027-07-01")]
    m = match_record(P, [PLANNED], ops, "harvesting", date(2027, 7, 2), date(2027, 7, 3))
    assert not m.ok and m.reason == "already_recorded"


def test_only_sowing_and_harvest_are_recorded_here():
    m = match_record(P, [PLANNED], [], "spraying", date(2026, 11, 10), TODAY)
    assert not m.ok and m.reason == "unsupported_type"


OLIVE = {"id": "urn:ngsi-ld:AgriCrop:acme:p1:olive", "type": "AgriCrop", "refAgriParcel": P,
         "status": "active", "cropRole": "main_crop", "species": "OLVEU", "cropLifecycle": "perennial",
         "plantingDate": "2010-03-01", "plantingDateSource": "manual"}


def _uproot(day):
    return _op("tillage", day, tillageType="uprooting")


def test_perennial_harvest_recorded():
    ops = [_op("harvesting", "2026-12-01")]
    m = match_record(P, [OLIVE], ops, "harvesting", date(2027, 1, 10), date(2027, 1, 11))
    assert m.ok and m.crop_id == OLIVE["id"] and m.harvest_campaign == "2026/27"


def test_perennial_first_harvest_recorded():
    m = match_record(P, [OLIVE], [], "harvesting", date(2026, 12, 1), date(2026, 12, 2))
    assert m.ok and m.crop_id == OLIVE["id"] and m.harvest_campaign == "2026/27"


def test_perennial_same_day_harvest_already_recorded():
    ops = [_op("harvesting", "2026-12-01")]
    m = match_record(P, [OLIVE], ops, "harvesting", date(2026, 12, 1), date(2026, 12, 2))
    assert not m.ok and m.reason == "already_recorded"


def test_perennial_harvest_requires_declared_start():
    olive = {k: v for k, v in OLIVE.items() if k not in ("plantingDate", "plantingDateSource")}
    m = match_record(P, [olive], [], "harvesting", date(2026, 12, 1), date(2026, 12, 2))
    assert not m.ok and m.reason == "no_crop_to_close"  # without a start the harvest lands on no stand


def test_annual_harvest_unchanged():
    m = match_record(P, [PLANNED], [_op("sowing", "2026-11-10")], "harvesting", date(2027, 7, 2), date(2027, 7, 3))
    assert m.ok and m.harvest_campaign is None


def test_uprooting_recorded():
    m = match_record(P, [OLIVE], [_op("harvesting", "2026-12-01")], "uprooting", date(2027, 3, 1), date(2027, 3, 2))
    assert m.ok and m.crop_id == OLIVE["id"]


def test_uprooting_refused_on_annual():
    m = match_record(P, [PLANNED], [_op("sowing", "2026-11-10")], "uprooting", date(2027, 3, 1), date(2027, 3, 2))
    assert not m.ok and m.reason == "not_perennial"


def test_uprooting_before_last_harvest():
    m = match_record(P, [OLIVE], [_op("harvesting", "2026-12-01")], "uprooting", date(2026, 11, 1), date(2027, 3, 2))
    assert not m.ok and m.reason == "date_before_last_harvest"


def test_uprooting_closed_cycle():
    m = match_record(P, [OLIVE], [_uproot("2027-03-01")], "uprooting", date(2027, 3, 5), date(2027, 3, 6))
    assert not m.ok and m.reason == "already_closed"


def test_uprooting_dated_before_an_existing_uprooting():
    m = match_record(P, [OLIVE], [_uproot("2027-03-01")], "uprooting", date(2027, 2, 1), date(2027, 3, 6))
    assert not m.ok and m.reason == "already_closed"


def test_uprooting_with_closed_and_open_stand_targets_the_open_one():
    old = dict(OLIVE, id="urn:ngsi-ld:AgriCrop:acme:p1:old", plantingDate="1990-03-01", species="VITVI")
    ops = [_op("tillage", "2020-01-10", tillageType="uprooting", hasAgriCrop=old["id"])]
    m = match_record(P, [old, OLIVE], ops, "uprooting", date(2027, 3, 1), date(2027, 3, 2))
    assert m.ok and m.crop_id == OLIVE["id"]
