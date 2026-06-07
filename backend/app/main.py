"""FastAPI application for nkz-module-field-operations."""
from fastapi import FastAPI
from .api.operations import router as operations_router
from .api.cue_bridge import router as cue_router

app = FastAPI(title="NKZ Field Operations", version="0.1.0")
app.include_router(operations_router)
app.include_router(cue_router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    return {"status": "ready"}
