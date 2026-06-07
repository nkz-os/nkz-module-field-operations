"""API package — route registration for field-operations."""

from fastapi import APIRouter

from app.api.operations import router as operations_router
from app.api.cue_bridge import router as cue_router

router = APIRouter()
router.include_router(operations_router)
router.include_router(cue_router)
