"""Tests for work order service."""
import pytest
from unittest.mock import patch, MagicMock
from app.services.work_order_service import create_external_work_order


class TestCreateExternalWorkOrder:
    def test_default_source_is_api(self):
        """External work orders get source=api by default."""
        with patch("app.services.work_order_service.create_operation") as mock_create, \
             patch("app.services.work_order_service.update_entity_attrs"):
            mock_create.return_value = {"id": "urn:ngsi-ld:AgriParcelOperation:t:abc"}

            create_external_work_order(
                tenant_id="test",
                parcel_id="urn:ngsi-ld:AgriParcel:t:p1",
                operation_type="spraying",
                work_order="EXT-001",
                operator="api@system.com",
            )

            assert mock_create.call_args[1]["source"] == "api"

    def test_odoo_source_sets_external_ref(self):
        """Odoo work orders have source=odoo and externalRef."""
        with patch("app.services.work_order_service.create_operation") as mock_create, \
             patch("app.services.work_order_service.update_entity_attrs"):
            mock_create.return_value = {"id": "urn:ngsi-ld:AgriParcelOperation:t:abc"}

            create_external_work_order(
                tenant_id="test",
                parcel_id="urn:ngsi-ld:AgriParcel:t:p1",
                operation_type="spraying",
                work_order="EXT-001",
                operator="api@system.com",
                source="odoo",
                external_ref="ODT-2026-0042",
            )

            assert mock_create.call_args[1]["source"] == "odoo"
            assert mock_create.call_args[1]["external_ref"] == "ODT-2026-0042"

    def test_odoo_source_sets_status_issued(self):
        """Odoo work orders should have status overridden to issued."""
        with patch("app.services.work_order_service.create_operation") as mock_create, \
             patch("app.services.work_order_service.update_entity_attrs") as mock_update:
            mock_create.return_value = {"id": "urn:ngsi-ld:AgriParcelOperation:t:abc"}

            result = create_external_work_order(
                tenant_id="test",
                parcel_id="urn:ngsi-ld:AgriParcel:t:p1",
                operation_type="spraying",
                work_order="EXT-001",
                operator="api@system.com",
                source="odoo",
            )

            mock_update.assert_called_once()
            status_update = mock_update.call_args[0][2]
            assert status_update["status"]["value"] == "issued"
            assert result["status"]["value"] == "issued"

    def test_manual_source_keeps_planned_status(self):
        """Manual source should keep the default planned status."""
        with patch("app.services.work_order_service.create_operation") as mock_create, \
             patch("app.services.work_order_service.update_entity_attrs") as mock_update:
            mock_create.return_value = {"id": "urn:ngsi-ld:AgriParcelOperation:t:abc"}

            create_external_work_order(
                tenant_id="test",
                parcel_id="urn:ngsi-ld:AgriParcel:t:p1",
                operation_type="spraying",
                work_order="EXT-001",
                operator="op@x.com",
                source="manual",
            )

            mock_update.assert_not_called()

    def test_invalid_source_raises(self):
        """Invalid source should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid source"):
            create_external_work_order(
                tenant_id="test",
                parcel_id="urn:ngsi-ld:AgriParcel:t:p1",
                operation_type="spraying",
                work_order="EXT-001",
                operator="op@x.com",
                source="invalid_source",
            )

    def test_sets_planned_date_and_assigned_to(self):
        """Optional planned_date and assigned_to should be passed through."""
        with patch("app.services.work_order_service.create_operation") as mock_create, \
             patch("app.services.work_order_service.update_entity_attrs"):
            mock_create.return_value = {"id": "urn:ngsi-ld:AgriParcelOperation:t:abc"}

            create_external_work_order(
                tenant_id="test",
                parcel_id="urn:ngsi-ld:AgriParcel:t:p1",
                operation_type="irrigation",
                work_order="EXT-002",
                operator="op@x.com",
                planned_date="2026-06-15T08:00:00Z",
                assigned_to="juan@example.com",
            )

            assert mock_create.call_args[1]["planned_date"] == "2026-06-15T08:00:00Z"
            assert mock_create.call_args[1]["assigned_to"] == "juan@example.com"
