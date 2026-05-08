from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import settings


PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}


async def auth_middleware(request: Request, call_next):
    if not settings.auth_enabled or request.method == "OPTIONS" or is_public_path(request.url.path):
        return await call_next(request)

    token = request.headers.get("x-api-key") or bearer_token(request.headers.get("authorization"))
    if token not in configured_api_keys():
        return JSONResponse({"detail": "Missing or invalid API key"}, status_code=401)

    return await call_next(request)


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith("/docs/") or path.startswith("/static/")


def configured_api_keys() -> set[str]:
    return {key.strip() for key in settings.api_keys.split(",") if key.strip()}


def bearer_token(header: str | None) -> str | None:
    if not header or not header.lower().startswith("bearer "):
        return None
    return header.split(" ", 1)[1].strip()
