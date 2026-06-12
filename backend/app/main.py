"""FastAPI application for nkz-module-field-operations."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .api.operations import router as operations_router
from .api.cue_bridge import router as cue_router
from .api.internal import router as internal_router
from .services.timeout_worker import check_stale_operations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(application: FastAPI):
    logger.info("Starting NKZ Field Operations module")
    task = asyncio.create_task(check_stale_operations())
    logger.info("Stale operation check worker started")
    yield
    task.cancel()
    logger.info("NKZ Field Operations module shutting down")


app = FastAPI(
    title="NKZ Field Operations",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(operations_router)
app.include_router(cue_router)
app.include_router(internal_router)


@app.get("/healthz")
@limiter.exempt
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
@limiter.exempt
async def readyz():
    return {"status": "ready"}
