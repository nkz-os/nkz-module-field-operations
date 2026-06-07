"""Configuration for nkz-module-field-operations."""
import os

ORION_URL = os.getenv("ORION_URL", "http://orion-ld-service:1026")
CONTEXT_URL = os.getenv("CONTEXT_URL", "http://api-gateway-service:5000/ngsi-ld-context.json")
CUE_API_URL = os.getenv("CUE_API_URL", "http://cue-service:5000")
ISOBUS_API_URL = os.getenv("ISOBUS_API_URL", "http://isobus-bridge-service:5000")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio-service:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_BUCKET = os.getenv("MINIO_LABELS_BUCKET", "nekazari-labels")

INCOMPLETE_TIMEOUT_HOURS = int(os.getenv("FIELD_OPS_INCOMPLETE_TIMEOUT_H", "24"))
LABEL_RETENTION_YEARS = 5

VALID_OPERATION_TYPES = [
    "sowing", "irrigation", "fertilization", "spraying", "tillage", "harvesting"
]
VALID_STATUSES = ["planned", "incomplete", "completed", "needs_review", "cancelled"]

REQUIRED_FIELDS = {
    "sowing": ["cropType", "variety", "seedingRate"],
    "irrigation": ["waterPerHectare"],
    "fertilization": ["fertilizerType", "fertilizerRate"],
    "spraying": ["productName", "productRate"],
    "tillage": ["tillageType"],
    "harvesting": ["harvestedWeight"],
}
