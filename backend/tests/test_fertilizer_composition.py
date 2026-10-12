"""Structured nutrient composition of fertilization operations."""
import math

import pytest

from app.fertilizer_composition import (
    COMPOSITION_FIELDS,
    NITROGEN_FORMS,
    CompositionError,
    normalize_composition,
)


def test_vocabulary_matches_the_spec():
    assert COMPOSITION_FIELDS == (
        "nitrogenContent", "phosphorusPentoxideContent", "potassiumOxideContent", "nitrogenForm",
    )
    assert NITROGEN_FORMS == ("ureic", "ammoniacal", "nitric", "organic", "mixed")


def test_contents_become_percent_properties_and_other_keys_pass_through():
    body = {"fertilizerRate": 300, "nitrogenContent": 15, "phosphorusPentoxideContent": 15.5,
            "potassiumOxideContent": 0, "nitrogenForm": "ammoniacal"}
    out = normalize_composition("fertilization", body)
    assert out["nitrogenContent"] == {"value": 15.0, "unitCode": "P1"}
    assert out["phosphorusPentoxideContent"] == {"value": 15.5, "unitCode": "P1"}
    assert out["potassiumOxideContent"] == {"value": 0.0, "unitCode": "P1"}
    assert out["nitrogenForm"] == "ammoniacal"
    assert out["fertilizerRate"] == 300
    assert body["nitrogenContent"] == 15  # the input is not mutated


def test_body_without_composition_is_returned_unchanged():
    body = {"fertilizerType": "urea", "fertilizerRate": 200}
    assert normalize_composition("fertilization", body) == body


def test_null_contents_are_dropped_not_written():
    out = normalize_composition(
        "fertilization", {"nitrogenContent": None, "nitrogenForm": None, "fertilizerRate": 1},
    )
    assert out == {"fertilizerRate": 1}


def test_null_composition_on_another_type_is_dropped_without_error():
    assert normalize_composition("sowing", {"nitrogenContent": None, "seedingRate": 180}) == {"seedingRate": 180}


@pytest.mark.parametrize("bad", [True, False, "15", [15], {"value": 15}, math.nan, math.inf, -math.inf])
def test_non_numeric_content_is_rejected(bad):
    with pytest.raises(CompositionError, match="nitrogenContent"):
        normalize_composition("fertilization", {"nitrogenContent": bad})


@pytest.mark.parametrize("bad", [-0.1, 100.1, 1000])
def test_content_outside_0_100_is_rejected(bad):
    with pytest.raises(CompositionError, match="between 0 and 100"):
        normalize_composition("fertilization", {"potassiumOxideContent": bad})


def test_contents_summing_over_100_are_rejected():
    with pytest.raises(CompositionError, match="exceed 100"):
        normalize_composition("fertilization", {
            "nitrogenContent": 50, "phosphorusPentoxideContent": 50, "potassiumOxideContent": 1,
        })


@pytest.mark.parametrize("grade", [(0, 60, 40), (33.3, 33.3, 33.4)])
def test_contents_summing_to_exactly_100_are_accepted(grade):
    # 0-60-40 is potassium metaphosphate, whose oxide forms add up to its whole mass.
    n, p, k = grade
    out = normalize_composition("fertilization", {
        "nitrogenContent": n, "phosphorusPentoxideContent": p, "potassiumOxideContent": k,
    })
    assert out["potassiumOxideContent"]["value"] == float(k)


def test_unknown_nitrogen_form_is_rejected():
    with pytest.raises(CompositionError, match="nitrogenForm"):
        normalize_composition("fertilization", {"nitrogenForm": "nitrate"})


@pytest.mark.parametrize("form", NITROGEN_FORMS)
def test_every_declared_nitrogen_form_is_accepted(form):
    assert normalize_composition("fertilization", {"nitrogenForm": form})["nitrogenForm"] == form


@pytest.mark.parametrize("op_type", ["sowing", "spraying", "harvesting"])
def test_composition_on_other_operation_types_is_rejected(op_type):
    with pytest.raises(CompositionError, match="fertilization"):
        normalize_composition(op_type, {"nitrogenContent": 10})


def test_sowing_body_passes_untouched():
    body = {"cropType": "wheat", "variety": "x", "seedingRate": 180, "irrigationRegime": "rainfed"}
    assert normalize_composition("sowing", body) == body
