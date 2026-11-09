"""build_attrs: validation and normalisation of the types recorded as completed facts."""
import pytest

from app.services.record_types import RecordError, build_attrs


def code(op, body):
    with pytest.raises(RecordError) as e:
        build_attrs(op, body)
    return e.value.code


def test_irrigation_rounds_to_three_decimals_and_accepts_comma():
    assert build_attrs("irrigation", {"waterPerHectare": "1234,56789"}) == {"waterPerHectare": 1234.568}


@pytest.mark.parametrize("v", [0, -1, "abc", True])
def test_irrigation_needs_a_positive_number(v):
    assert code("irrigation", {"waterPerHectare": v}) == "invalid_number"


def test_irrigation_missing():
    assert code("irrigation", {}) == "missing_fields"


def test_fertilization_kg_default():
    a = build_attrs("fertilization", {"fertilizerType": " Urea ", "rate": 150})
    assert a == {"fertilizerType": "Urea", "fertilizerRate": 150.0, "fertilizerRateInput": 150.0,
                 "fertilizerRateUnit": "kg/ha"}


def test_fertilization_tonnes():
    a = build_attrs("fertilization", {"fertilizerType": "Manure", "rate": 2.5, "rateUnit": "t/ha"})
    assert a["fertilizerRate"] == 2500.0 and a["fertilizerRateInput"] == 2.5 and "fertilizerDensity" not in a


def test_fertilization_litres_use_density():
    a = build_attrs("fertilization", {"fertilizerType": "N32", "rate": 200, "rateUnit": "L/ha",
                                      "density": 1.32, "densityAssumed": True})
    assert a["fertilizerRate"] == 264.0 and a["fertilizerDensity"] == 1.32
    assert a["fertilizerDensityAssumed"] is True and a["fertilizerRateUnit"] == "L/ha"


def test_fertilization_cubic_metres():
    a = build_attrs("fertilization", {"fertilizerType": "Slurry", "rate": 30, "rateUnit": "m3/ha", "density": 1.0})
    assert a["fertilizerRate"] == 30000.0 and a["fertilizerDensityAssumed"] is False


@pytest.mark.parametrize("unit", ["L/ha", "m3/ha"])
def test_volume_needs_density(unit):
    assert code("fertilization", {"fertilizerType": "x", "rate": 1, "rateUnit": unit}) == "missing_fields"


@pytest.mark.parametrize("d", [0.49, 2.01, "x"])
def test_density_range(d):
    assert code("fertilization", {"fertilizerType": "x", "rate": 1, "rateUnit": "L/ha", "density": d}) == "invalid_number"


def test_fertilization_unknown_unit():
    assert code("fertilization", {"fertilizerType": "x", "rate": 1, "rateUnit": "lb/ac"}) == "invalid_unit"


def test_fertilization_composition():
    a = build_attrs("fertilization", {"fertilizerType": "NPK", "rate": 300,
                                      "composition": {"n": 15, "p": 15, "k": 15}})
    assert a["nitrogenContent"] == {"value": 15.0, "unitCode": "P1"}
    assert a["phosphorusPentoxideContent"] == {"value": 15.0, "unitCode": "P1"}
    assert a["potassiumOxideContent"] == {"value": 15.0, "unitCode": "P1"}
    assert a["fertilizerComposition"] == "15-15-15"


@pytest.mark.parametrize("comp", [{"n": 120}, {"n": 60, "p": 60}, {"n": "a"}, "15-15-15"])
def test_bad_composition(comp):
    assert code("fertilization", {"fertilizerType": "x", "rate": 1, "composition": comp}) == "invalid_fertilizer_composition"


@pytest.mark.parametrize("v", ["", "   ", None])
def test_text_required(v):
    assert code("fertilization", {"fertilizerType": v, "rate": 1}) == "missing_fields"


def test_text_limits():
    assert code("spraying", {"productName": "x" * 121, "productRate": 1}) == "invalid_text"
    assert code("spraying", {"productName": "a\x00b", "productRate": 1}) == "invalid_text"


def test_spraying_defaults_and_target():
    a = build_attrs("spraying", {"productName": "Glyfo", "productRate": "1,5", "target": " weeds "})
    assert a == {"productName": "Glyfo", "productRate": 1.5, "productRateUnit": "L/ha", "target": "weeds"}


def test_spraying_unit():
    assert build_attrs("spraying", {"productName": "x", "productRate": 5, "productRateUnit": "mL/ha"})["productRateUnit"] == "mL/ha"
    assert code("spraying", {"productName": "x", "productRate": 5, "productRateUnit": "oz"}) == "invalid_unit"


def test_tillage():
    assert build_attrs("tillage", {"tillageType": "roller_crimper", "depth": 12.5}) == {
        "tillageType": "roller_crimper", "tillageDepth": 12.5}
    assert build_attrs("tillage", {"tillageType": "ploughing"}) == {"tillageType": "ploughing"}


@pytest.mark.parametrize("t", ["uprooting", "Ploughing", "x"])
def test_tillage_type_rejected(t):
    assert code("tillage", {"tillageType": t}) == "invalid_tillage_type"


@pytest.mark.parametrize("d", [0, -3, 100.1, "x"])
def test_tillage_depth(d):
    assert code("tillage", {"tillageType": "ploughing", "depth": d}) == "invalid_number"


def test_haymaking_and_baling():
    assert build_attrs("haymaking", {"swathType": "raking"}) == {"swathType": "raking"}
    assert code("haymaking", {}) == "missing_fields"
    assert code("haymaking", {"swathType": "x"}) == "invalid_choice"
    assert build_attrs("baling", {"baleCount": "12", "baleType": "round"}) == {"baleCount": 12, "baleType": "round"}
    assert code("baling", {"baleCount": 2.5, "baleType": "round"}) == "invalid_number"
    assert code("baling", {"baleCount": 0, "baleType": "round"}) == "invalid_number"
    assert code("baling", {"baleCount": 2, "baleType": "cube"}) == "invalid_choice"
    assert code("baling", {"baleCount": 2}) == "missing_fields"


def test_scouting():
    assert build_attrs("scouting", {"notes": " aphids "}) == {"platformType": "manual", "notes": "aphids"}
    assert build_attrs("scouting", {"notes": "x", "platformType": "drone"})["platformType"] == "drone"
    assert code("scouting", {}) == "missing_fields"
    assert code("scouting", {"notes": "x", "platformType": "boat"}) == "invalid_choice"


def test_notes_limit():
    assert code("irrigation", {"waterPerHectare": 1, "notes": "x" * 501}) == "invalid_notes"


def test_sowing_is_not_handled_here():
    assert code("sowing", {}) == "unsupported_type"
