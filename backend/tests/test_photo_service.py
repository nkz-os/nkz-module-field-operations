"""Tests for photo upload service."""
import pytest
from unittest.mock import MagicMock, patch

from app.services.photo_service import upload_label_photo


class TestUploadLabelPhoto:
    def test_rejects_oversized_file(self):
        """Files over 10MB should raise ValueError."""
        with pytest.raises(ValueError, match="File too large"):
            upload_label_photo("tenant", "op:id", b"x" * (11 * 1024 * 1024), "photo.jpg")

    def test_rejects_invalid_extension(self):
        """Non-image extensions should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid file type"):
            upload_label_photo("tenant", "op:id", b"data", "file.pdf")

    def test_rejects_dangerous_extension(self):
        """Executable extensions should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid file type"):
            upload_label_photo("tenant", "op:id", b"data", "photo.exe")

    @patch("app.services.photo_service.Minio")
    def test_upload_success_jpg(self, mock_minio_class):
        """JPG file uploads to correct MinIO path and returns URL."""
        mock_minio = MagicMock()
        mock_minio_class.return_value = mock_minio
        mock_minio.bucket_exists.return_value = True

        url = upload_label_photo(
            "test-tenant",
            "urn:ngsi-ld:AgriParcelOperation:t:id123",
            b"fake-image-data",
            "label.jpg",
        )

        # Verify bucket and path
        mock_minio.put_object.assert_called_once()
        call_args = mock_minio.put_object.call_args
        # First 3 positional: bucket_name, object_name, data
        assert call_args[0][0] == "nekazari-labels"
        assert "test-tenant" in call_args[0][1]
        assert "id123" in call_args[0][1]
        # content_type in kwargs
        assert call_args[1]["content_type"] == "image/jpeg"

        # Verify URL format
        assert url.startswith("/api/field-operations/photos/field-operations/")

    @patch("app.services.photo_service.Minio")
    def test_upload_creates_bucket_if_missing(self, mock_minio_class):
        """If bucket doesn't exist, it should be created."""
        mock_minio = MagicMock()
        mock_minio_class.return_value = mock_minio
        mock_minio.bucket_exists.return_value = False

        upload_label_photo("t", "op:id", b"data", "photo.png")

        mock_minio.make_bucket.assert_called_once_with("nekazari-labels")
