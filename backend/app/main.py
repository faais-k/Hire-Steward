import os
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.app.api.routes.compensation import router as compensation_router
from backend.app.api.routes.candidate_evidence import router as candidate_evidence_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.job_discovery import router as job_discovery_router
from backend.app.api.routes.application_tracking import router as application_tracking_router
from backend.app.db.session import make_session_factory
from backend.app.adapters.storage import EvidenceStorage
from backend.app.evidence_config import EvidenceSettings, evidence_settings_from_environment

ALLOWED_CLIENT_HOSTS = {
    "127.0.0.1",
    "::1",
    "::ffff:127.0.0.1",
    "localhost",
    "testclient",
}

ALLOWED_ORIGIN_HOSTS = {
    "localhost",
    "127.0.0.1",
    "::1",
}


class LocalClientOnlyMiddleware:
    """Enforce local loopback client execution.

    TrustedHostMiddleware validates only the HTTP Host header, which can be
    spoofed if the server listens on a non-loopback network interface.
    This middleware verifies the ASGI client socket IP and any cross-origin
    headers to ensure only local loopback callers can access the service.
    """

    def __init__(self, app: ASGIApp, allowed_hosts: set[str] | None = None) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts or ALLOWED_CLIENT_HOSTS

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"}:
            client = scope.get("client")
            client_host = client[0] if client else None
            if not client_host or client_host not in self.allowed_hosts:
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "LOCAL_LOOPBACK_REQUIRED"},
                )
                await response(scope, receive, send)
                return

            # Reject untrusted cross-origin requests
            headers = dict(scope.get("headers", []))
            origin_raw = headers.get(b"origin")
            if origin_raw is not None:
                origin_str = origin_raw.decode("latin1", errors="ignore").strip()
                if origin_str and origin_str != "null":
                    try:
                        parsed = urlsplit(origin_str)
                        origin_host = parsed.hostname
                    except Exception:
                        origin_host = None
                    if not origin_host or origin_host.lower() not in ALLOWED_ORIGIN_HOSTS:
                        response = JSONResponse(
                            status_code=403,
                            content={"detail": "LOCAL_LOOPBACK_REQUIRED"},
                        )
                        await response(scope, receive, send)
                        return
                elif origin_str == "null":
                    response = JSONResponse(
                        status_code=403,
                        content={"detail": "LOCAL_LOOPBACK_REQUIRED"},
                    )
                    await response(scope, receive, send)
                    return

        await self.app(scope, receive, send)


def create_app(
    *,
    database_url: str | None = None,
    session_factory: sessionmaker[Session] | None = None,
    evidence_settings: EvidenceSettings | None = None,
) -> FastAPI:
    resolved_database_url = database_url or os.getenv("DATABASE_URL")
    app = FastAPI(
        title="Hire-steward API",
        description=(
            "Hire-steward is a local-first, user-controlled job discovery and "
            "application-management platform. Public compensation assessments "
            "remain review-required and cannot authorize application submission."
        ),
        version="0.1.0",
    )
    app.state.session_factory = (
        session_factory
        if session_factory is not None
        else make_session_factory(resolved_database_url)
        if resolved_database_url
        else None
    )
    app.state.evidence_settings = evidence_settings or evidence_settings_from_environment()
    app.state.evidence_storage = (
        EvidenceStorage(app.state.evidence_settings)
        if app.state.evidence_settings is not None
        else None
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "[::1]"],
    )
    app.add_middleware(LocalClientOnlyMiddleware)
    app.include_router(health_router)
    app.include_router(compensation_router)
    app.include_router(candidate_evidence_router)
    app.include_router(job_discovery_router)
    app.include_router(application_tracking_router)

    # Mount static frontend workbench if directory exists
    frontend_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
    )
    if os.path.isdir(frontend_dir):
        @app.get("/workbench")
        def serve_workbench():
            return FileResponse(os.path.join(frontend_dir, "index.html"))

        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    @app.exception_handler(RequestValidationError)
    async def invalid_request_handler(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "INVALID_REQUEST"})

    return app


app = create_app()
