"""Validation and normalisation of the operation types recorded as completed facts.

``build_attrs`` turns the request body of one type into the attributes stored on the
AgriParcelOperation, or raises ``RecordError`` with the contract's code (spec 3.2).
Sowing, harvesting and uprooting do not go through here: they use the crop window.
"""

from __future__ import annotations

import math
import re

from ..fertilizer_composition import CompositionError, normalize_composition

NEW_TYPES = ("irrigation", "fertilization", "spraying", "tillage", "haymaking", "baling", "scouting")

# Stored vocabularies, as the web form (OperationDetail.tsx) writes them.
TILLAGE_TYPES = ("ploughing", "harrowing", "cultivating", "rolling", "subsoiling", "roller_crimper", "mowing")
SWATH_TYPES = ("tedding", "raking", "mowing")
BALE_TYPES = ("round", "square")
PLATFORM_TYPES = ("drone", "rover", "satellite", "manual")
DEFAULT_PLATFORM = "manual"

FERTILIZER_UNITS = ("kg/ha", "t/ha", "L/ha", "m3/ha")
SPRAY_UNITS = ("L/ha", "kg/ha", "g/ha", "mL/ha")
_KG_PER_UNIT = {"kg/ha": 1.0, "t/ha": 1000.0, "m3/ha": 1000.0, "L/ha": 1.0}  # volume ones x density
_VOLUME_UNITS = ("L/ha", "m3/ha")
DENSITY_MIN, DENSITY_MAX = 0.5, 2.0
TEXT_MAX = 120
NOTES_MAX = 500
DEPTH_MAX_CM = 100
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_DECIMALS = 3


class RecordError(Exception):
    def __init__(self, code: str, detail: str, status: int = 422):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail, self.status = code, detail, status


MAX_VALUE = 1e9


def _round(value: float) -> float:
    """Rounded to 3 decimals; a value that rounds to 0 or leaves the range is refused."""
    out = round(value, _DECIMALS)
    if not math.isfinite(out) or out <= 0 or out > MAX_VALUE:
        raise RecordError("invalid_number", "value must be a positive number")
    return out


def _number(field: str, raw) -> float:
    # Same rule as _positive in api/record.py (that module imports this one), plus an upper bound.
    if isinstance(raw, bool):
        raise RecordError("invalid_number", f"{field} must be a positive number")
    try:
        value = float(str(raw).replace(",", "."))
    except ValueError:
        value = float("nan")
    if not math.isfinite(value) or value <= 0 or value > MAX_VALUE:
        raise RecordError("invalid_number", f"{field} must be a positive number of at most {MAX_VALUE:g}")
    return value


def _empty(raw) -> bool:
    return raw is None or (isinstance(raw, str) and not raw.strip())


def _require(body: dict, *fields: str) -> None:
    missing = [f for f in fields if _empty(body.get(f))]
    if missing:
        raise RecordError("missing_fields", f"missing: {', '.join(missing)}")


def _text(field: str, raw, *, required: bool = True) -> str | None:
    if _empty(raw):
        if required:
            raise RecordError("missing_fields", f"missing: {field}")
        return None
    if not isinstance(raw, str):
        raise RecordError("invalid_text", f"{field} must be text")
    value = raw.strip()
    if len(value) > TEXT_MAX or _CONTROL.search(value):
        raise RecordError("invalid_text", f"{field} must be 1-{TEXT_MAX} characters without control characters")
    return value


def _unit(field: str, raw, allowed: tuple, default: str) -> str:
    if _empty(raw):
        return default
    if not isinstance(raw, str) or raw.strip() not in allowed:
        raise RecordError("invalid_unit", f"{field} must be one of: {', '.join(allowed)}")
    return raw.strip()


def _choice(field: str, raw, allowed: tuple) -> str:
    if not isinstance(raw, str) or raw.strip() not in allowed:
        raise RecordError("invalid_choice", f"{field} must be one of: {', '.join(allowed)}")
    return raw.strip()


def _notes(body: dict, required: bool = False) -> dict:
    raw = body.get("notes")
    if _empty(raw):
        if required:
            raise RecordError("missing_fields", "missing: notes")
        return {}
    if not isinstance(raw, str) or len(raw) > NOTES_MAX:
        raise RecordError("invalid_notes", f"notes must be text of at most {NOTES_MAX} characters")
    return {"notes": raw.strip()}


def _fertilization(body: dict) -> dict:
    _require(body, "fertilizerType", "rate")
    attrs = {"fertilizerType": _text("fertilizerType", body["fertilizerType"])}
    rate = _number("rate", body["rate"])
    unit = _unit("rateUnit", body.get("rateUnit"), FERTILIZER_UNITS, "kg/ha")
    factor = _KG_PER_UNIT[unit]
    attrs["fertilizerRateInput"] = _round(rate)
    attrs["fertilizerRateUnit"] = unit
    if unit in _VOLUME_UNITS:
        if _empty(body.get("density")):
            raise RecordError("missing_fields", f"missing: density (required with {unit})")
        density = _number("density", body["density"])
        if not DENSITY_MIN <= density <= DENSITY_MAX:
            raise RecordError("invalid_number", f"density must be between {DENSITY_MIN} and {DENSITY_MAX} kg/L")
        factor *= density
        attrs["fertilizerDensity"] = _round(density)
        assumed = body.get("densityAssumed", False)
        if not isinstance(assumed, bool):
            raise RecordError("invalid_choice", "densityAssumed must be true or false")
        attrs["fertilizerDensityAssumed"] = assumed
    organic = body.get("organic")
    if organic is not None:
        if not isinstance(organic, bool):
            raise RecordError("invalid_choice", "organic must be true or false")
        attrs["organicFertilizer"] = organic
    attrs["fertilizerRate"] = _round(rate * factor)  # always kg/ha: what carbon and FaST read

    composition = body.get("composition")
    if composition is not None:
        if not isinstance(composition, dict):
            raise RecordError("invalid_fertilizer_composition", "composition must be an object {n, p, k}")
        mapped = {name: composition[key] for key, name in (
            ("n", "nitrogenContent"), ("p", "phosphorusPentoxideContent"), ("k", "potassiumOxideContent"))
            if composition.get(key) is not None}
        try:
            normalized = normalize_composition("fertilization", mapped)
        except CompositionError as exc:
            raise RecordError("invalid_fertilizer_composition", str(exc)) from exc
        attrs.update(normalized)
        if mapped:
            # A nutrient not given is "?", as the web grade (formatGrade) writes it, never 0.
            grade = [f"{normalized[n]['value']:g}" if n in normalized else "?" for n in (
                "nitrogenContent", "phosphorusPentoxideContent", "potassiumOxideContent")]
            attrs["fertilizerComposition"] = "-".join(grade)
    return attrs


def _spraying(body: dict) -> dict:
    _require(body, "productName", "productRate")
    attrs = {"productName": _text("productName", body["productName"]),
             "productRate": _round(_number("productRate", body["productRate"])),
             "productRateUnit": _unit("productRateUnit", body.get("productRateUnit"), SPRAY_UNITS, "L/ha")}
    target = _text("target", body.get("target"), required=False)
    if target:
        attrs["target"] = target
    return attrs


def _tillage(body: dict) -> dict:
    _require(body, "tillageType")
    raw = body["tillageType"]
    if not isinstance(raw, str) or raw not in TILLAGE_TYPES:
        raise RecordError("invalid_tillage_type", f"tillageType must be one of: {', '.join(TILLAGE_TYPES)}")
    attrs = {"tillageType": raw}
    if not _empty(body.get("depth")):
        depth = _number("depth", body["depth"])
        if depth > DEPTH_MAX_CM:
            raise RecordError("invalid_number", f"depth must be at most {DEPTH_MAX_CM} cm")
        attrs["tillageDepth"] = _round(depth)
    return attrs


def _count(raw) -> int:
    value = _number("baleCount", raw)
    if value != int(value):
        raise RecordError("invalid_number", "baleCount must be a whole number")
    return int(value)


def build_attrs(operation_type: str, body: dict) -> dict:
    """Stored attributes of one of ``NEW_TYPES`` (crop-derived ones are added by the caller)."""
    if operation_type == "irrigation":
        _require(body, "waterPerHectare")
        attrs = {"waterPerHectare": _round(_number("waterPerHectare", body["waterPerHectare"]))}
    elif operation_type == "fertilization":
        attrs = _fertilization(body)
    elif operation_type == "spraying":
        attrs = _spraying(body)
    elif operation_type == "tillage":
        attrs = _tillage(body)
    elif operation_type == "haymaking":
        _require(body, "swathType")
        attrs = {"swathType": _choice("swathType", body["swathType"], SWATH_TYPES)}
    elif operation_type == "baling":
        _require(body, "baleCount", "baleType")
        attrs = {"baleCount": _count(body["baleCount"]),
                 "baleType": _choice("baleType", body["baleType"], BALE_TYPES)}
    elif operation_type == "scouting":
        platform = DEFAULT_PLATFORM if _empty(body.get("platformType")) else body["platformType"]
        attrs = {"platformType": _choice("platformType", platform, PLATFORM_TYPES)}
    else:
        raise RecordError("unsupported_type", f"operation_type must be one of: {', '.join(NEW_TYPES)}")
    attrs.update(_notes(body, required=operation_type == "scouting"))
    return attrs
