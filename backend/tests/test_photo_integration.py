"""Integration tests for label-photo endpoint (via TestClient).

Mocks Orion-LD (SyncOrionClient) and MinIO to test request/response wiring.
"""
import io
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(operation_id: str, status: str = "incomplete") -> dict:
    """Return a minimal AgriParcelOperation entity dict as Orion-LD returns it."""
    return {
        "id": operation_id,
        "type": "AgriParcelOperation",
        "status": {"type": "Property", "value": status},
        "operationType": {"type": "Property", "value": "spraying"},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLabelPhotoUploadIntegration:
    """Integration tests for POST /operations/{id}/label-photo."""

    @patch("app.api.operations.get_entity")
    @patch("app.api.operations.update_entity_attrs")
    @patch("app.services.photo_service.Minio")
    def test_upload_label_photo_success(
        self, mock_minio_class, mock_update, mock_get_entity
    ):
        """Upload a label photo for an existing operation returns 200 with URL."""
        op_id = "urn:ngsi-ld:AgriParcelOperation:t:abc123"
        mock_get_entity.return_value = _make_entity(op_id)
        mock_minio = MagicMock()
        mock_minio_class.return_value = mock_minio
        mock_minio.bucket_exists.return_value = True

        resp = client.post(
            f"/api/field-operations/operations/{op_id}/label-photo",
            files={"label_photo": ("test.jpg", b"fake-image-data", "image/jpeg")},
            headers={"X-Tenant-ID": "test-tenant"},
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "url" in data
        assert data["url"].startswith("/api/field-operations/photos/field-operations/")

        # Verify entity attr was updated with labelPhoto
        mock_update.assert_called_once()
        args, kwargs = mock_update.call_args
        assert args[0] == "test-tenant"
        assert args[1] == op_id
        assert "labelPhoto" in args[2]
        assert args[2]["labelPhoto"]["type"] == "Property"
        assert args[2]["labelPhoto"]["value"]["url"] == data["url"]

    @patch("app.api.operations.get_entity")
    def test_upload_label_photo_404(self, mock_get_entity):
        """Upload for a non-existent operation returns 404."""
        op_id = "urn:ngsi-ld:AgriParcelOperation:t:nonexistent"
        mock_get_entity.return_value = None  # entity not found

        resp = client.post(
            f"/api/field-operations/operations/{op_id}/label-photo",
            files={"label_photo": ("photo.jpg", b"data", "image/jpeg")},
            headers={"X-Tenant-ID": "test-tenant"},
        )

        assert resp.status_code == 404, resp.text

    @patch("app.api.operations.get_entity")
    @patch("app.services.photo_service.Minio")
    def test_upload_label_photo_oversized(
        self, mock_minio_class, mock_get_entity
    ):
        """Upload a file over 10MB returns 400."""
        op_id = "urn:ngsi-ld:AgriParcelOperation:t:abc123"
        mock_get_entity.return_value = _make_entity(op_id)
        mock_minio = MagicMock()
        mock_minio_class.return_value = mock_minio

        resp = client.post(
            f"/api/field-operations/operations/{op_id}/label-photo",
            files={"label_photo": ("big.jpg", b"x" * (11 * 1024 * 1024), "image/jpeg")},
            headers={"X-Tenant-ID": "test-tenant"},
        )

        assert resp.status_code == 400, resp.text
        assert "File too large" in resp.text

    @patch("app.api.operations.get_entity")
    @patch("app.api.operations.update_entity_attrs")
    @patch("app.services.photo_service.Minio")
    def test_upload_label_photo_no_tenant_header(self, mock_minio_class, mock_update, mock_get_entity):
        """Missing tenant header falls back to empty string (no 500)."""
        op_id = "urn:ngsi-ld:AgriParcelOperation:t:abc123"
        mock_get_entity.return_value = _make_entity(op_id)
        mock_minio = MagicMock()
        mock_minio_class.return_value = mock_minio
        mock_minio.bucket_exists.return_value = True

        resp = client.post(
            f"/api/field-operations/operations/{op_id}/label-photo",
            files={"label_photo": ("photo.jpg", b"data", "image/jpeg")},
            # No X-Tenant-ID header
        )

        # Should succeed (empty tenant, but operation exists and MinIO works)
        assert resp.status_code == 200, resp.text

    @patch("app.api.operations.get_entity")
    @patch("app.api.operations.update_entity_attrs")
    @patch("app.services.photo_service.Minio")
    def test_upload_label_photo_disallowed_extension(
        self, mock_minio_class, mock_update, mock_get_entity
    ):
        """Upload a .exe file returns 400."""
        op_id = "urn:ngsi-ld:AgriParcelOperation:t:abc123"
        mock_get_entity.return_value = _make_entity(op_id)

        resp = client.post(
            f"/api/field-operations/operations/{op_id}/label-photo",
            files={"label_photo": ("malware.exe", b"data", "application/x-msdownload")},
            headers={"X-Tenant-ID": "test-tenant"},
        )

        assert resp.status_code == 400, resp.text
        assert "Invalid file type" in resp.text


class TestLabelPhotoServingIntegration:
    """Integration tests for GET /photos/{path:path}."""

    @patch("app.api.operations.get_label_photo")
    @patch("app.api.operations._get_tenant")
    def test_serve_photo_success(self, mock_get_tenant, mock_get_photo):
        """GET with valid path returns the image content."""
        mock_get_tenant.return_value = "test-tenant"
        mock_get_photo.return_value = (b"fake-image-content", "image/jpeg")

        resp = client.get(
            "/api/field-operations/photos/field-operations/test-tenant/abc123/label_a1b2.jpg",
            headers={"X-Tenant-ID": "test-tenant"},
        )

        assert resp.status_code == 200, resp.text
        assert resp.content == b"fake-image-content"
        assert resp.headers["content-type"] == "image/jpeg"

    @patch("app.api.operations.get_label_photo")
    @patch("app.api.operations._get_tenant")
    def test_serve_photo_wrong_tenant(self, mock_get_tenant, mock_get_photo):
        """GET with mismatched tenant returns 403."""
        mock_get_tenant.return_value = "other-tenant"

        resp = client.get(
            "/api/field-operations/photos/field-operations/test-tenant/abc123/label_a1b2.jpg",
            headers={"X-Tenant-ID": "other-tenant"},
        )

        assert resp.status_code == 403, resp.text

    @patch("app.api.operations.get_label_photo")
    @patch("app.api.operations._get_tenant")
    def test_serve_photo_not_found(self, mock_get_tenant, mock_get_photo):
        """GET with non-existent object key returns 404."""
        mock_get_tenant.return_value = "test-tenant"
        mock_get_photo.side_effect = FileNotFoundError("Photo not found")

        resp = client.get(
            "/api/field-operations/photos/field-operations/test-tenant/abc123/missing.jpg",
            headers={"X-Tenant-ID": "test-tenant"},
        )

        assert resp.status_code == 404, resp.text

    @patch("app.api.operations.get_label_photo")
    @patch("app.api.operations._get_tenant")
    def test_serve_photo_invalid_path(self, mock_get_tenant, mock_get_photo):
        """GET with malformed path (too few segments) returns 403."""
        mock_get_tenant.return_value = "test-tenant"

        resp = client.get(
            "/api/field-operations/photos/too-short",
            headers={"X-Tenant-ID": "test-tenant"},
        )

        assert resp.status_code == 403, resp.text
