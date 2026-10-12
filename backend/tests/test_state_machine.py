"""Tests for the AgriParcelOperation state machine."""
import pytest
from app.state_machine import can_transition, validate_completion_fields, validate_sowing_method


class TestCanTransition:
    def test_planned_to_incomplete_allowed(self):
        result = can_transition("planned", "incomplete", "user")
        assert result.allowed
        assert result.new_status == "incomplete"

    def test_planned_to_completed_blocked(self):
        result = can_transition("planned", "completed", "user")
        assert not result.allowed

    def test_issued_to_planned_allowed_for_manager(self):
        result = can_transition("issued", "planned", "field_manager")
        assert result.allowed

    def test_issued_to_planned_allowed_for_external_api(self):
        result = can_transition("issued", "planned", "external_api")
        assert result.allowed

    def test_issued_to_planned_blocked_for_user(self):
        result = can_transition("issued", "planned", "user")
        assert not result.allowed

    def test_issued_to_cancelled_allowed(self):
        result = can_transition("issued", "cancelled", "field_manager")
        assert result.allowed

    def test_completed_is_terminal(self):
        result = can_transition("completed", "cancelled", "tenant_admin")
        assert not result.allowed

    def test_cancelled_is_terminal(self):
        result = can_transition("cancelled", "planned", "field_manager")
        assert not result.allowed

    def test_unknown_status_returns_false(self):
        result = can_transition("unknown", "planned", "user")
        assert not result.allowed
        assert "Unknown status" in result.reason


class TestValidateCompletionFields:
    def test_missing_fields_returned(self):
        entity = {"operationType": {"value": "spraying"}}
        missing = validate_completion_fields("spraying", entity)
        assert "productName" in missing
        assert "productRate" in missing

    def test_no_missing_when_all_present(self):
        entity = {
            "operationType": {"value": "spraying"},
            "productName": {"value": "Amistar"},
            "productRate": {"value": 0.5},
        }
        missing = validate_completion_fields("spraying", entity)
        assert missing == []

    def test_irrigation_requires_water_per_ha(self):
        entity = {"operationType": {"value": "irrigation"}}
        missing = validate_completion_fields("irrigation", entity)
        assert "waterPerHectare" in missing


class TestValidateSowingMethod:
    def test_absent_is_fine(self):
        assert validate_sowing_method("sowing", {"cropType": "wheat"}) is None

    def test_valid_values_on_sowing(self):
        assert validate_sowing_method("sowing", {"sowingMethod": "direct"}) is None
        assert validate_sowing_method("sowing", {"sowingMethod": "conventional"}) is None

    def test_property_form_is_unwrapped(self):
        assert validate_sowing_method("sowing", {"sowingMethod": {"type": "Property", "value": "direct"}}) is None

    def test_unknown_value_rejected(self):
        assert validate_sowing_method("sowing", {"sowingMethod": "no-till"}) == \
            "sowingMethod must be one of: direct, conventional"

    def test_only_on_sowing(self):
        assert validate_sowing_method("tillage", {"sowingMethod": "direct"}) == \
            "sowingMethod is only valid on sowing operations"

    def test_empty_value_is_absent(self):
        assert validate_sowing_method("sowing", {"sowingMethod": ""}) is None
