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


def test_harvest_of_a_perennial_is_refused():
    vine = dict(PLANNED, id="urn:ngsi-ld:AgriCrop:t:p1:vine", status="active", cropLifecycle="perennial",
                harvestDate="2027-09-30")
    sown = {"id": "s", "hasAgriParcel": P, "operationType": "sowing", "status": "completed", "endedAt": "2026-11-10"}
    m = match_record(P, [vine], [sown], "harvesting", date(2027, 9, 20), date(2027, 9, 21))
    assert not m.ok and m.reason == "perennial_harvest_unsupported"
