"""Photo upload service — stores label photos in MinIO."""
import io
import logging
import os
import uuid

from minio import Minio
from minio.error import S3Error

from ..config import (
    MINIO_ENDPOINT,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY,
    MINIO_BUCKET,
)

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".heic": "image/heic",
    ".heif": "image/heif",
}


def _get_minio_client() -> Minio:
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,  # dentro del cluster
    )


def upload_label_photo(
    tenant_id: str,
    operation_id: str,
    file_data: bytes,
    filename: str,
) -> str:
    """Upload a label photo to MinIO. Returns accessible URL path."""
    if len(file_data) > MAX_FILE_SIZE:
        raise ValueError(
            f"File too large ({len(file_data)} bytes, max {MAX_FILE_SIZE})"
        )

    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Invalid file type: {ext}")

    op_short = operation_id.split(":")[-1]
    object_key = (
        f"field-operations/{tenant_id}/{op_short}/"
        f"label_{uuid.uuid4().hex[:8]}{ext}"
    )

    try:
        client = _get_minio_client()

        if not client.bucket_exists(MINIO_BUCKET):
            client.make_bucket(MINIO_BUCKET)

        client.put_object(
            MINIO_BUCKET,
            object_key,
            io.BytesIO(file_data),
            length=len(file_data),
            content_type=MIME_MAP.get(ext, "application/octet-stream"),
        )
    except S3Error as e:
        logger.error("MinIO upload failed: %s", e)
        raise RuntimeError(f"Failed to upload photo: {e.message or str(e)}") from e

    url = f"/api/field-operations/photos/{object_key}"
    logger.info("Uploaded label photo: %s", object_key)
    return url
