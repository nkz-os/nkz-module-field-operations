"""Tests for the AgriParcelOperation state machine."""
import pytest
from app.state_machine import can_transition, validate_completion_fields


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
