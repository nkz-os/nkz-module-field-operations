"""FastAPI application for nkz-module-field-operations."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .auth import ensure_signature_enforced, gateway_identity
from .api.operations import router as operations_router
from .api.cue_bridge import router as cue_router
from .api.internal import router as internal_router
from .api.plan_summary import router as plan_summary_router
from .api.record import router as record_router
from .services.timeout_worker import check_stale_operations
from .services.irrigation_bridge import irrigation_bridge_loop
from .services import crop_cycles_runtime
from nkz_platform_sdk.lifecycle import lifecycle_hint_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(application: FastAPI):
    logger.info("Starting NKZ Field Operations module")
    ensure_signature_enforced()
    task = asyncio.create_task(check_stale_operations())
    logger.info("Stale operation check worker started")
    bridge_task = asyncio.create_task(irrigation_bridge_loop())
    crop_tasks = crop_cycles_runtime.start()
    yield
    task.cancel()
    bridge_task.cancel()
    for t in crop_tasks:
        t.cancel()
    logger.info("NKZ Field Operations module shutting down")


app = FastAPI(
    title="NKZ Field Operations",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# User routes: identity verified against the gateway signature (the tenant header is
# only trusted once its X-Auth-Signature checks out).
_user = [Depends(gateway_identity)]
app.include_router(operations_router, dependencies=_user)
app.include_router(cue_router, dependencies=_user)
app.include_router(record_router, dependencies=_user)
app.include_router(internal_router)
# Install/uninstall hint from entity-manager: only triggers a subscription reconcile.
app.include_router(lifecycle_hint_router("/internal/lifecycle", crop_cycles_runtime.reconcile_subscriptions))
app.include_router(plan_summary_router)


@app.get("/healthz")
@limiter.exempt
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
@limiter.exempt
async def readyz():
    return {"status": "ready"}
