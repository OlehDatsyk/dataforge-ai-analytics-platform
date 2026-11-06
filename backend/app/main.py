"""FastAPI application: routers, security middleware, error handling, and optional static hosting."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api import analyst, anomalies, auth, charts, connections, datasets, overview, reports, workspaces
from .config import get_settings
from .services import jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("dataforge")
for noisy in ("httpx", "httpx2", "anthropic"):
    logging.getLogger(noisy).setLevel(logging.WARNING)  # request URLs do not belong in application logs

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
# Multipart overhead allowed on top of the configured file size limit.
UPLOAD_OVERHEAD = 1024 * 1024


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    settings.data_path.mkdir(parents=True, exist_ok=True)
    try:
        jobs.resume_interrupted()
    except Exception:
        logger.error("The database is not ready. Run 'alembic upgrade head' (setup does this for you).")
    yield
    jobs.shutdown()


app = FastAPI(
    title="DataForge AI API",
    version=__version__,
    description="API for the DataForge AI analytics platform. Authenticate with POST /api/auth/login, which sets session cookies.",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

settings_at_start = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings_at_start.origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Workspace-Id"],
)


def _origin_allowed(request: Request, origin: str) -> bool:
    """Accept the configured front-end origins and same-origin requests."""
    if origin in get_settings().origins:
        return True
    return urlsplit(origin).netloc == request.headers.get("host")


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    path = request.url.path
    if request.method in UNSAFE:
        origin = request.headers.get("origin")
        if origin and not _origin_allowed(request, origin):
            return JSONResponse({"detail": "This origin is not allowed."}, status_code=403)
    if request.method == "POST" and path == "/api/datasets":
        settings = get_settings()
        length = request.headers.get("content-length")
        if length is None:
            return JSONResponse({"detail": "Upload requests must declare their size."}, status_code=411)
        if not length.isdigit() or int(length) > settings.max_upload_bytes + UPLOAD_OVERHEAD:
            return JSONResponse({"detail": f"The file exceeds the {settings.max_upload_mb} MB upload limit."}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # The interactive API docs load their own assets, so the strict policy excludes that page.
    if path != "/api/docs":
        response.headers["Content-Security-Policy"] = CSP
    if get_settings().is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError):
    """Return readable validation messages without echoing submitted values."""
    messages = []
    for error in exc.errors()[:8]:
        location = ".".join(str(p) for p in error.get("loc", []) if p not in {"body", "query", "path"})
        message = error.get("msg", "Invalid value.").removeprefix("Value error, ")
        messages.append(f"{location}: {message}" if location else message)
    return JSONResponse({"detail": "; ".join(messages)}, status_code=422)


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    """Log the exception type only, and show a generic message: details could expose data or paths."""
    logger.error("Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
    return JSONResponse({"detail": "An unexpected error occurred."}, status_code=500)


@app.get("/api/health", tags=["Overview"])
def health():
    return {"status": "ok", "version": __version__}


for module in (auth, workspaces, datasets, charts, analyst, anomalies, reports, connections, overview):
    app.include_router(module.router, prefix="/api")


@app.exception_handler(StarletteHTTPException)
async def http_handler(request: Request, exc: StarletteHTTPException):
    """Serve the single-page app for browser routes when a built front end is present."""
    if exc.status_code == 404 and not request.url.path.startswith("/api") and request.method == "GET":
        dist = get_settings().frontend_dist_path
        if dist.exists():
            relative = request.url.path.lstrip("/")
            candidate = (dist / relative).resolve()
            if relative and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
                return FileResponse(candidate)
            index = dist / "index.html"
            if index.exists():
                return FileResponse(index)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))
