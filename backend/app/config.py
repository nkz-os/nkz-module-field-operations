"""Configuration for nkz-module-field-operations."""
import os

ORION_URL = os.getenv("ORION_URL", "http://orion-ld-service:1026")
CONTEXT_URL = os.getenv("CONTEXT_URL", "http://api-gateway-service:5000/ngsi-ld-context.json")
CUE_API_URL = os.getenv("CUE_API_URL", "http://cue-service:5000")
ISOBUS_API_URL = os.getenv("ISOBUS_API_URL", "http://isobus-bridge-service:5000")
BIOORCHESTRATOR_API_URL = os.getenv(
    "BIOORCHESTRATOR_API_URL", "http://bioorchestrator-api-service:8420"
)
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio-service:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_BUCKET = os.getenv("MINIO_LABELS_BUCKET", "nekazari-labels")

MODULE_ID = "field-operations"
INCOMPLETE_TIMEOUT_HOURS = int(os.getenv("FIELD_OPS_INCOMPLETE_TIMEOUT_H", "24"))
LABEL_RETENTION_YEARS = 5

VALID_SOURCES = ["manual", "odoo", "api", "isobus"]
ODOO_EXTERNAL_REF_PREFIX = os.getenv("ODOO_EXTERNAL_REF_PREFIX", "ODT-")

VALID_OPERATION_TYPES = [
    "sowing", "irrigation", "fertilization", "spraying", "tillage",
    "harvesting", "haymaking", "baling", "scouting",
]
VALID_STATUSES = ["planned", "issued", "incomplete", "completed", "needs_review", "cancelled"]

REQUIRED_FIELDS = {
    "sowing": ["cropType", "variety", "seedingRate"],
    "irrigation": ["waterPerHectare"],
    "fertilization": ["fertilizerType", "fertilizerRate"],
    "spraying": ["productName", "productRate"],
    "tillage": ["tillageType"],
    "harvesting": ["harvestedWeight"],
    "haymaking": ["cropType", "swathType"],
    "baling": ["cropType", "baleType", "baleCount"],
    "scouting": ["platformType"],
}

# How a sowing was done, as the ESYRCE records it for cereals (MAPA, ESYRCE 2022, 3.6): directly
# on the previous crop's stubble, or after tillage. Read by crop simulation (residue mulch).
SOWING_METHODS = ["direct", "conventional"]

INTERNAL_SERVICE_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "")

# Crop-cycle writer (hasAgriCrop, actual sowing/termination dates). Off until the
# platform switches it over from the core.
CROP_CYCLES_WRITER_ENABLED = os.getenv("CROP_CYCLES_WRITER_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")
CROP_CYCLES_NOTIFY_URL = os.getenv(
    "CROP_CYCLES_NOTIFY_URL", "http://field-operations-api-service:8420/internal/notify/crop-cycles"
)
