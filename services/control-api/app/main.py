import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.apps import router as apps_router
from app.api.routes.actions import router as actions_router
from app.api.routes.evaluations import router as evaluations_router
from app.api.routes.health import router as health_router
from app.api.routes.incidents import router as incidents_router
from app.api.routes.memory import router as memory_router
from app.api.routes.observability import router as observability_router
from app.api.routes.repairs import router as repairs_router
from app.api.routes.sandboxes import router as sandboxes_router
from app.api.routes.scenarios import router as scenarios_router
from app.apps import ensure_app_schema
from app.cicd import ensure_cicd_schema
from app.core.config import settings
from app.core.db import execute_schema_bootstrap, open_connection
from app.core.logging import configure_logging, tracing_middleware
from app.core.security import auth_middleware
from app.customizations import ensure_customization_schema
from app.evaluation import ensure_evaluation_schema
from app.memory import ensure_memory_schema
from app.monitoring import monitor_loop
from app.repair import ensure_repair_schema
from app.rollout import ensure_rollout_schema


SCHEMA_INITIALIZERS = (
    ensure_app_schema,
    ensure_memory_schema,
    ensure_repair_schema,
    ensure_cicd_schema,
    ensure_rollout_schema,
    ensure_evaluation_schema,
    ensure_customization_schema,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    execute_schema_bootstrap()
    ensure_extension_schemas()
    monitor_task = start_monitor_if_enabled()
    yield
    await stop_monitor(monitor_task)


def ensure_extension_schemas() -> None:
    with open_connection() as conn:
        for initializer in SCHEMA_INITIALIZERS:
            initializer(conn)


def start_monitor_if_enabled() -> asyncio.Task | None:
    if not settings.run_monitor_in_api:
        return None
    return asyncio.create_task(monitor_loop(open_connection, settings.monitor_interval_seconds))


async def stop_monitor(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Self-Healing Runtime Control API",
    description="Control plane for sandboxes, target health, and incident foundations.",
    version="0.1.0",
    lifespan=lifespan,
)

app.middleware("http")(tracing_middleware)
app.middleware("http")(auth_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(apps_router)
app.include_router(sandboxes_router)
app.include_router(incidents_router)
app.include_router(scenarios_router)
app.include_router(observability_router)
app.include_router(actions_router)
app.include_router(memory_router)
app.include_router(repairs_router)
app.include_router(evaluations_router)


@app.get("/")
def root():
    return {
        "service": "self-healing-control-api",
        "capability": "guarded-runtime-mitigation",
        "docs": "/docs",
    }
