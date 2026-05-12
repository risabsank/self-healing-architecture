from fastapi import APIRouter, Depends
from psycopg import Connection

from app.core.config import settings
from app.core.db import get_connection
from app.monitoring import run_all_health_checks

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health(conn: Connection = Depends(get_connection)):
    db_ok = True
    db_error = None

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            cur.fetchone()
    except Exception as exc:
        db_ok = False
        db_error = str(exc)

    target_results = []
    if db_ok:
        target_results = await run_all_health_checks(conn)

    target_healthy = all(result["status"] == "healthy" for result in target_results)

    return {
        "service": "self-healing-control-api",
        "status": "healthy" if db_ok and target_healthy else "degraded",
        "checks": {
            "database": {
                "ok": db_ok,
                "error": db_error,
            },
            "targets": target_results,
            "reasoning": {
                "llm_enabled": settings.llm_reasoning_enabled,
                "anthropic_key_configured": bool(settings.anthropic_api_key),
                "model": settings.anthropic_model if settings.llm_reasoning_enabled else None,
            },
        },
    }
