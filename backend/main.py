"""GenieWatch — FastAPI entry point.

Observability for Databricks Genie Spaces. Read-only.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env.local", override=True)
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.services.auth import (
    is_running_on_databricks_apps,
    set_obo_user_token,
    clear_obo_user_token,
)

# Routers
from backend.routers.auth import router as auth_router
from backend.routers.spaces import router as spaces_router
from backend.routers.cost import router as cost_router
from backend.routers.usage import router as usage_router
from backend.routers.resources import router as resources_router
from backend.routers.evals import router as evals_router
from backend.routers.settings import router as settings_router
from backend.routers.admin import router as admin_router


class OBOAuthMiddleware(BaseHTTPMiddleware):
    """Set the per-request OBO WorkspaceClient from x-forwarded-access-token."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path.startswith("/api/"):
            token = request.headers.get("x-forwarded-access-token", "")
            if token:
                set_obo_user_token(token)
            request.state.user_token = token
        else:
            request.state.user_token = ""

        response = await call_next(request)
        is_streaming = getattr(response, "media_type", "") == "text/event-stream"
        if not is_streaming:
            clear_obo_user_token()
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


app = FastAPI(
    title="GenieWatch",
    description="Observability for Databricks Genie Spaces",
    version="0.1.0",
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(OBOAuthMiddleware)

if not is_running_on_databricks_apps():
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )


@app.on_event("startup")
async def startup() -> None:
    from backend.services.lakebase import init_pool
    await init_pool()


@app.on_event("shutdown")
async def shutdown() -> None:
    from backend.services.lakebase import close_pool
    await close_pool()


# Routers
app.include_router(auth_router)
app.include_router(spaces_router)
app.include_router(cost_router)
app.include_router(usage_router)
app.include_router(resources_router)
app.include_router(evals_router)
app.include_router(settings_router)
app.include_router(admin_router)


# Static SPA
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
FRONTEND_DIST_RESOLVED = FRONTEND_DIST.resolve()

if FRONTEND_DIST.exists():
    if (FRONTEND_DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    _NO_CACHE = {"Cache-Control": "no-store, must-revalidate"}

    @app.get("/")
    async def serve_root():
        return FileResponse(FRONTEND_DIST / "index.html", headers=_NO_CACHE)

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        static_file = (FRONTEND_DIST / full_path).resolve()
        if static_file.is_file() and static_file.is_relative_to(FRONTEND_DIST_RESOLVED):
            return FileResponse(static_file)
        return FileResponse(FRONTEND_DIST / "index.html", headers=_NO_CACHE)
else:
    @app.get("/")
    async def serve_root_debug():
        return {
            "error": "Frontend not built or not deployed",
            "expected_path": str(FRONTEND_DIST),
            "hint": "Run: cd frontend && npm ci && npm run build",
        }


def main() -> None:
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=not is_running_on_databricks_apps(),
    )


if __name__ == "__main__":
    main()
