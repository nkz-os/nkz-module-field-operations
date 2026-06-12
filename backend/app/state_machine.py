"""State machine for AgriParcelOperation lifecycle."""
from dataclasses import dataclass
from typing import Optional
from .config import REQUIRED_FIELDS

ALLOWED_TRANSITIONS = {
    "issued":       ["planned", "cancelled"],  # NEW: external work order, needs manager review
    "planned":      ["incomplete", "cancelled"],
    "incomplete":   ["completed", "needs_review"],
    "needs_review": ["completed", "cancelled"],
    "completed":    [],
    "cancelled":    [],
}

ACTORS_FOR_TRANSITION = {
    ("issued", "planned"):          ["field_manager", "tenant_admin", "external_api"],
    ("issued", "cancelled"):        ["field_manager", "tenant_admin", "external_api"],
    ("planned", "incomplete"):      ["user", "field_manager", "tenant_admin", "isobus_api_key"],
    ("planned", "cancelled"):       ["field_manager", "tenant_admin"],
    ("incomplete", "completed"):    ["user", "field_manager", "tenant_admin", "isobus_api_key"],
    ("incomplete", "needs_review"): ["system"],
    ("needs_review", "completed"):  ["field_manager", "tenant_admin"],
    ("needs_review", "cancelled"):  ["field_manager", "tenant_admin"],
}


@dataclass
class TransitionResult:
    allowed: bool
    new_status: Optional[str] = None
    reason: str = ""


def can_transition(current_status: str, target_status: str, actor_role: str) -> TransitionResult:
    """Check if a status transition is allowed."""
    if current_status not in ALLOWED_TRANSITIONS:
        return TransitionResult(False, reason=f"Unknown status: {current_status}")

    allowed_targets = ALLOWED_TRANSITIONS.get(current_status, [])
    if target_status not in allowed_targets:
        return TransitionResult(
            False,
            reason=f"Cannot transition from '{current_status}' to '{target_status}'. Allowed: {allowed_targets}"
        )

    allowed_actors = ACTORS_FOR_TRANSITION.get((current_status, target_status), [])
    if actor_role not in allowed_actors:
        return TransitionResult(
            False,
            reason=f"Role '{actor_role}' not authorized for '{current_status} -> {target_status}'"
        )

    return TransitionResult(True, new_status=target_status)


def validate_completion_fields(operation_type: str, entity: dict) -> list[str]:
    """Return list of missing required fields for completion."""
    required = REQUIRED_FIELDS.get(operation_type, [])
    missing = []
    for field in required:
        val = entity.get(field)
        if val is None:
            missing.append(field)
        elif isinstance(val, dict) and val.get("value") in (None, ""):
            missing.append(field)
    return missing
