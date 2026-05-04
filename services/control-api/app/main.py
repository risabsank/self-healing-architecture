import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.incidents import router as incidents_router
from app.api.routes.sandboxes import router as sandboxes_router
from app.core.config import settings
from app.core.db import execute_schema_bootstrap, open_connection
from app.monitoring import monitor_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    execute_schema_bootstrap()
    monitor_task = asyncio.create_task(
        monitor_loop(open_connection, settings.monitor_interval_seconds)
    )
    yield
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Self-Healing Runtime Control API",
    description="Control plane for sandboxes, target health, and incident foundations.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(sandboxes_router)
app.include_router(incidents_router)


@app.get("/")
def root():
    return {
        "service": "self-healing-control-api",
        "phase": "system-foundation",
        "docs": "/docs",
    }
