"""Structured nutrient composition of a fertilization operation.

The field notebook keeps the free-text grade (`fertilizerComposition`) and adds the
numbers a nutrient plan computes with: N, P2O5 and K2O as % of the product (oxide
forms, as fertilizer labels declare them) and the form of the N.
"""
from __future__ import annotations

import math
from typing import Any

NUTRIENT_CONTENT_FIELDS = ("nitrogenContent", "phosphorusPentoxideContent", "potassiumOxideContent")
COMPOSITION_FIELDS = NUTRIENT_CONTENT_FIELDS + ("nitrogenForm",)
NITROGEN_FORMS = ("ureic", "ammoniacal", "nitric", "organic", "mixed")
PERCENT_UNIT = "P1"  # UN/CEFACT Rec 20: percent
_SUM_TOLERANCE = 1e-9


class CompositionError(ValueError):
    """The submitted composition cannot be stored."""


def _content(field: str, raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise CompositionError(f"{field} must be a number (% of product)")
    if isinstance(raw, int):
        if not 0 <= raw <= 100:  # int range check first: math.isfinite overflows on huge ints
            raise CompositionError(f"{field} must be between 0 and 100 % of product")
    elif not math.isfinite(raw):
        raise CompositionError(f"{field} must be a number (% of product)")
    if not 0 <= raw <= 100:
        raise CompositionError(f"{field} must be between 0 and 100 % of product")
    return float(raw)


def normalize_composition(operation_type: str, body: dict, stored: dict | None = None) -> dict:
    """Return a copy of `body` with the composition validated and ready for NGSI-LD.

    Null composition fields are dropped (a cleared field is "not recorded", and Orion
    rejects null). Contents become {"value": x, "unitCode": "P1"}. Raises
    CompositionError for anything that cannot be stored. `stored` is the entity as
    Orion returns it: its contents absent from `body` count toward the sum, unvalidated
    and not written back.
    """
    out = {k: v for k, v in body.items() if not (k in COMPOSITION_FIELDS and v is None)}
    present = [f for f in COMPOSITION_FIELDS if f in out]
    if not present:
        return out
    if operation_type != "fertilization":
        raise CompositionError(f"{', '.join(present)} only apply to fertilization operations")
    total = 0.0
    for field in NUTRIENT_CONTENT_FIELDS:
        if field in out:
            value = _content(field, out[field])
            total += value
            out[field] = {"value": value, "unitCode": PERCENT_UNIT}
        elif stored:
            prev = (stored.get(field) or {}).get("value")
            if isinstance(prev, (int, float)) and not isinstance(prev, bool):
                total += prev
    if total > 100 + _SUM_TOLERANCE:
        raise CompositionError(
            "nitrogenContent + phosphorusPentoxideContent + potassiumOxideContent "
            "cannot exceed 100 % of product"
        )
    if "nitrogenForm" in out and out["nitrogenForm"] not in NITROGEN_FORMS:
        raise CompositionError(f"nitrogenForm must be one of {', '.join(NITROGEN_FORMS)}")
    return out
