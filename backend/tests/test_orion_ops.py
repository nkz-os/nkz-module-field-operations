"""Tests for app.orion_ops — SyncOrionClient migration."""
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import requests

from app.orion_ops import (
    create_operation,
    get_entity,
    update_entity_attrs,
    start_operation,
    complete_operation,
    enrich_from_isobus,
    query_operations,
    extrapolate_to_full_parcel,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    """Return a MagicMock that mimics SyncOrionClient."""
    client = MagicMock()
    client.context_url = "http://test-context.example.com/ngsi-ld-context.json"
    client.base_url = "http://orion-ld-service:1026"
    client.timeout = 30.0

    # _headers returns a dict that the caller can inspect
    def _headers(content_type="application/json"):
        return {
            "NGSILD-Tenant": "test-tenant",
            "Fiware-Service": "test-tenant",
            "Fiware-ServicePath": "/",
            "Content-Type": content_type,
        }
    client._headers = _headers

    # _url builds a full URL from a path
    def _url(path):
        return f"http://orion-ld-service:1026{path}"
    client._url = _url

    # _session is a MagicMock so we can assert calls on it for raw requests
    client._session = MagicMock()
    return client


@pytest.fixture(autouse=True)
def patch_client(mock_client):
    """Patch SyncOrionClient in app.orion_ops for every test."""
    with patch("app.orion_ops.SyncOrionClient", return_value=mock_client) as patched:
        yield patched


# ---------------------------------------------------------------------------
# create_operation
# ---------------------------------------------------------------------------

class TestCreateOperation:
    def test_create_operation_basic(self, mock_client):
        """Minimal call produces a valid NGSI-LD entity dict."""
        result = create_operation(
            "test-tenant", "parcel:001", "spraying", "WO-001", "op@x.com",
        )

        entity = mock_client.create_entity.call_args[0][0]
        assert entity["id"].startswith("urn:ngsi-ld:AgriParcelOperation:test-tenant:")
        assert entity["type"] == "AgriParcelOperation"
        assert entity["hasAgriParcel"] == {"type": "Relationship", "object": "parcel:001"}
        assert entity["operationType"] == {"type": "Property", "value": "spraying"}
        assert entity["workOrder"] == {"type": "Property", "value": "WO-001"}
        assert entity["status"] == {"type": "Property", "value": "planned"}
        assert entity["operator"] == {"type": "Property", "value": "op@x.com"}
        assert entity["dataSource"] == {"type": "Property", "value": "manual"}
        assert entity["@context"] == ["http://test-context.example.com/ngsi-ld-context.json"]
        assert "dateCreated" in entity
        assert "modificationLog" in entity

        # The returned dict matches the entity sent
        assert result is entity

    def test_create_operation_uses_hasAgriParcel_not_ref(self, mock_client):
        """Must use FIWARE-standard hasAgriParcel (not deprecated refAgriParcel)."""
        create_operation("test", "parcel:x", "spraying", "WO-001", "op@x.com")
        entity = mock_client.create_entity.call_args[0][0]
        assert "hasAgriParcel" in entity
        assert "refAgriParcel" not in entity

    def test_create_operation_with_tractor_and_implement(self, mock_client):
        """Relationships for tractor_id and implement_id."""
        create_operation(
            "test", "parcel:x", "tillage", "WO-002", "op@x.com",
            tractor_id="tractor:abc", implement_id="implement:xyz",
        )
        entity = mock_client.create_entity.call_args[0][0]
        assert entity["usesTractor"] == {"type": "Relationship", "object": "tractor:abc"}
        assert entity["usesImplement"] == {"type": "Relationship", "object": "implement:xyz"}

    def test_create_operation_invalid_type(self):
        """Raises ValueError for unknown operation types."""
        with pytest.raises(ValueError, match="Invalid operationType"):
            create_operation("test", "parcel:x", "invalid_op", "WO-001", "op@x.com")

    def test_create_operation_with_planned_date(self, mock_client):
        """plannedDate should be DateTime-typed, not plain string."""
        create_operation(
            "test", "parcel:x", "spraying", "WO-001", "op@x.com",
            planned_date="2026-06-15T10:00:00Z",
            assigned_to="juan@example.com",
            source="odoo",
            external_ref="ODT-0042",
        )

        entity = mock_client.create_entity.call_args[0][0]
        assert entity["plannedDate"]["value"]["@type"] == "DateTime"
        assert entity["plannedDate"]["value"]["@value"] == "2026-06-15T10:00:00Z"
        assert entity["assignedTo"]["value"] == "juan@example.com"
        assert entity["source"]["value"] == "odoo"
        assert entity["externalRef"]["value"] == "ODT-0042"

    def test_create_operation_orion_failure(self, mock_client):
        """Raises RuntimeError when Orion-LD returns an error."""
        mock_client.create_entity.side_effect = requests.HTTPError(
            "400 Client Error",
            response=MagicMock(status_code=400, text="Bad Request"),
        )
        with pytest.raises(RuntimeError, match="Orion-LD create failed"):
            create_operation("test", "parcel:x", "spraying", "WO-001", "op@x.com")


# ---------------------------------------------------------------------------
# get_entity
# ---------------------------------------------------------------------------

class TestGetEntity:
    def test_get_entity_found(self, mock_client):
        mock_client.get_entity.return_value = {"id": "entity:1", "type": "AgriParcelOperation"}
        result = get_entity("test-tenant", "entity:1")
        assert result == {"id": "entity:1", "type": "AgriParcelOperation"}
        mock_client.get_entity.assert_called_once_with("entity:1")

    def test_get_entity_not_found(self, mock_client):
        mock_client.get_entity.side_effect = requests.HTTPError(
            "404 Not Found",
            response=MagicMock(status_code=404, text="Not Found"),
        )
        result = get_entity("test-tenant", "entity:missing")
        assert result is None


# ---------------------------------------------------------------------------
# update_entity_attrs
# ---------------------------------------------------------------------------

class TestUpdateEntityAttrs:
    def test_update_entity_attrs_success(self, mock_client):
        mock_response = MagicMock(status_code=204, text="")
        mock_client._session.patch.return_value = mock_response

        attrs = {"status": {"type": "Property", "value": "completed"}}
        result = update_entity_attrs("test-tenant", "entity:1", attrs)

        assert result == attrs
        mock_client._session.patch.assert_called_once()
        url = mock_client._session.patch.call_args[0][0]
        assert "entity:1/attrs" in url

    def test_update_entity_attrs_failure(self, mock_client):
        mock_client._session.patch.return_value = MagicMock(status_code=400, text="Bad")
        with pytest.raises(RuntimeError, match="Orion-LD patch failed"):
            update_entity_attrs("test-tenant", "entity:1", {"status": {"type": "Property", "value": "x"}})


# ---------------------------------------------------------------------------
# start_operation
# ---------------------------------------------------------------------------

class TestStartOperation:
    def test_start_operation(self, mock_client):
        mock_client._session.patch.return_value = MagicMock(status_code=204, text="")
        result = start_operation("test-tenant", "op:1")

        assert result["status"] == {"type": "Property", "value": "incomplete"}
        assert "startedAt" in result


# ---------------------------------------------------------------------------
# complete_operation
# ---------------------------------------------------------------------------

class TestCompleteOperation:
    def test_complete_operation(self, mock_client):
        mock_client._session.patch.return_value = MagicMock(status_code=204, text="")
        result = complete_operation("test-tenant", "op:1")

        assert result["status"] == {"type": "Property", "value": "completed"}
        assert "endedAt" in result

    def test_complete_operation_with_extra_attrs(self, mock_client):
        mock_client._session.patch.return_value = MagicMock(status_code=204, text="")
        extra = {"productName": "Glyphosate", "productRate": {"value": 2.5, "unitCode": "KGM"}}
        result = complete_operation("test-tenant", "op:1", extra_attrs=extra)

        assert result["productName"] == {"type": "Property", "value": "Glyphosate"}
        assert result["productRate"] == {"type": "Property", "value": 2.5, "unitCode": "KGM"}


# ---------------------------------------------------------------------------
# enrich_from_isobus
# ---------------------------------------------------------------------------

class TestEnrichFromIsobus:
    def test_enrich_with_partial_data(self, mock_client):
        mock_client._session.patch.return_value = MagicMock(status_code=204, text="")
        isobus = {"fuelUsed": 12.5, "areaCovered": 2.3}
        result = enrich_from_isobus("test-tenant", "op:1", isobus)

        assert "fuelUsed" in result
        assert result["fuelUsed"]["value"] == 12.5
        assert "areaCovered" in result

    def test_enrich_empty_data(self, mock_client):
        result = enrich_from_isobus("test-tenant", "op:1", {})
        assert result == {}


# ---------------------------------------------------------------------------
# query_operations
# ---------------------------------------------------------------------------

class TestQueryOperations:
    def test_query_by_parcel(self, mock_client):
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = [{"id": "op:1", "type": "AgriParcelOperation"}]
        mock_client._session.get.return_value = mock_response

        results = query_operations("test-tenant", parcel_id="parcel:001")
        assert len(results) == 1
        assert results[0]["id"] == "op:1"

        # Verify params passed to _session.get
        _call = mock_client._session.get.call_args
        params = _call[1]["params"]
        assert params["type"] == "AgriParcelOperation"
        assert params["options"] == "keyValues"
        assert 'hasAgriParcel=="parcel:001"' in params["q"]

    def test_query_all(self, mock_client):
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = []
        mock_client._session.get.return_value = mock_response

        results = query_operations("test-tenant")
        assert results == []


# ---------------------------------------------------------------------------
# extrapolate_to_full_parcel
# ---------------------------------------------------------------------------

class TestExtrapolateToFullParcel:
    def test_extrapolate(self, mock_client):
        mock_client.get_entity.return_value = {
            "id": "op:1",
            "areaCovered": {"value": 2.0, "unitCode": "HAR"},
            "modificationLog": {"value": []},
        }
        mock_client._session.patch.return_value = MagicMock(status_code=204, text="")

        result = extrapolate_to_full_parcel("test-tenant", "op:1", 10.0)
        assert result["areaCovered"]["value"] == 10.0
        assert "modificationLog" in result

    def test_extrapolate_missing_area(self, mock_client):
        mock_client.get_entity.return_value = {"id": "op:1", "areaCovered": {"value": 0}}
        with pytest.raises(ValueError, match="no areaCovered data"):
            extrapolate_to_full_parcel("test-tenant", "op:1", 10.0)

    def test_extrapolate_entity_not_found(self, mock_client):
        mock_client.get_entity.side_effect = requests.HTTPError(
            "404 Not Found",
            response=MagicMock(status_code=404, text="Not Found"),
        )
        with pytest.raises(ValueError, match="not found"):
            extrapolate_to_full_parcel("test-tenant", "op:1", 10.0)

    def test_extrapolate_missing_unit_omits_unit_code(self, mock_client):
        """When unitCode is missing, no unitCode field should be sent."""
        mock_client.get_entity.return_value = {
            "id": "op:1",
            "areaCovered": {"value": 2.0, "unitCode": "HAR"},
            "fuelUsed": {"value": 10.0},  # No unitCode
        }
        mock_client._session.patch.return_value = MagicMock(status_code=204, text="")

        extrapolate_to_full_parcel("test-tenant", "op:1", 10.0)

        patch_call = mock_client._session.patch.call_args
        body = patch_call[1]["json"]
        # fuelUsed should exist but without unitCode
        assert "value" in body["fuelUsed"]
        assert "unitCode" not in body["fuelUsed"]
