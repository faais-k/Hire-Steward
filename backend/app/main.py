from contextlib import asynccontextmanager
import logging
import os
import uuid
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.app.adapters.storage import EvidenceStorage
from backend.app.api.routes.application_tracking import router as application_tracking_router
from backend.app.api.routes.candidate_evidence import router as candidate_evidence_router
from backend.app.api.routes.candidate_profile import router as candidate_profile_router
from backend.app.api.routes.answer_bank import router as answer_bank_router
from backend.app.api.routes.compensation import router as compensation_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.job_discovery import router as job_discovery_router
from backend.app.api.routes.system import router as system_router
from backend.app.api.routes.settings import router as settings_router
from backend.app.api.routes.source_registry import router as source_registry_router
from backend.app.api.routes.ai_router import router as ai_router
from backend.app.api.routes.data_portability import router as data_portability_router
from backend.app.db.session import make_session_factory
from backend.app.evidence_config import EvidenceSettings, evidence_settings_from_environment
from backend.app.logging_config import configure_logging, correlation_id_ctx

configure_logging()

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


class CorrelationIdMiddleware:
    """Assign or propagate X-Correlation-ID for every request and set contextvar."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            cid_bytes = headers.get(b"x-correlation-id")
            if cid_bytes:
                cid = cid_bytes.decode("utf-8", errors="ignore").strip()
            else:
                cid = uuid.uuid4().hex

            token = correlation_id_ctx.set(cid)

            async def send_wrapper(message: dict[str, Any]) -> None:
                if message["type"] == "http.response.start":
                    headers_list = list(message.get("headers", []))
                    headers_list.append((b"x-correlation-id", cid.encode("utf-8")))
                    message["headers"] = headers_list
                await send(message)

            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                correlation_id_ctx.reset(token)
            return

        await self.app(scope, receive, send)


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


logger = logging.getLogger("hire_steward.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI application lifespan managing background worker and scheduler services."""
    session_factory = getattr(app.state, "session_factory", None)
    enable_background = getattr(app.state, "enable_background_services", None)
    if enable_background is None:
        env_val = os.getenv("ENABLE_BACKGROUND_SERVICES")
        if env_val is not None:
            enable_background = env_val.lower() in ("true", "1", "yes")
        else:
            # Default to enabled for live server, but disable for automated test runs
            # to prevent daemon thread contention on ephemeral SQLite databases.
            enable_background = "PYTEST_CURRENT_TEST" not in os.environ

    # Safety: Never run background services against protected workspace database
    if session_factory is not None and enable_background:
        try:
            bind = session_factory.kw.get("bind") or getattr(session_factory, "bind", None)
            if (
                bind
                and hasattr(bind, "url")
                and bind.url
                and bind.url.database == "jobpilot_workspace"
            ):
                enable_background = False
                logger.info(
                    "Background services disabled for protected database jobpilot_workspace."
                )
        except Exception:
            pass

    if session_factory is not None and enable_background:
        try:
            from backend.app.services.background_worker import BackgroundWorker
            from backend.app.services.scheduler import LocalScheduler

            worker = BackgroundWorker(session_factory=session_factory)
            app.state.background_worker = worker
            worker.start()

            scheduler = LocalScheduler(session_factory=session_factory)
            app.state.local_scheduler = scheduler
            scheduler.start()
            logger.info("BackgroundWorker and LocalScheduler initialized.")
        except Exception as exc:
            logger.warning("Could not initialize background services on startup: %s", exc)

    yield

    scheduler = getattr(app.state, "local_scheduler", None)
    if scheduler is not None:
        try:
            scheduler.stop()
        except Exception as exc:
            logger.warning("Error stopping LocalScheduler: %s", exc)

    worker = getattr(app.state, "background_worker", None)
    if worker is not None:
        try:
            worker.stop(drain_timeout_seconds=5.0)
        except Exception as exc:
            logger.warning("Error stopping BackgroundWorker: %s", exc)


def create_app(
    *,
    database_url: str | None = None,
    session_factory: sessionmaker[Session] | None = None,
    evidence_settings: EvidenceSettings | None = None,
    enable_background_services: bool | None = None,
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
        lifespan=lifespan,
    )
    if enable_background_services is not None:
        app.state.enable_background_services = enable_background_services
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
        allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"],
    )
    app.add_middleware(LocalClientOnlyMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    app.include_router(health_router)
    app.include_router(system_router)
    app.include_router(compensation_router)
    app.include_router(candidate_evidence_router)
    app.include_router(candidate_profile_router)
    app.include_router(answer_bank_router)
    app.include_router(job_discovery_router)
    app.include_router(application_tracking_router)
    app.include_router(settings_router)
    app.include_router(source_registry_router)
    app.include_router(ai_router)
    app.include_router(data_portability_router)

    # Mount static frontend workbench (preferring compiled production React dist)
    frontend_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
    )
    dist_dir = os.path.join(frontend_dir, "dist")
    static_dir = dist_dir if os.path.isdir(dist_dir) else frontend_dir
    index_file = os.path.join(static_dir, "index.html")
    if os.path.isdir(static_dir) and os.path.isfile(index_file):
        @app.get("/workbench")
        def serve_workbench():
            return FileResponse(index_file)

        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    @app.exception_handler(RequestValidationError)
    async def invalid_request_handler(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "INVALID_REQUEST"})

    return app


app = create_app()
