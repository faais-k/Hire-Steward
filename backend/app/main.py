import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.app.api.routes.compensation import router as compensation_router
from backend.app.api.routes.candidate_evidence import router as candidate_evidence_router
from backend.app.api.routes.health import router as health_router
from backend.app.db.session import make_session_factory
from backend.app.adapters.storage import EvidenceStorage
from backend.app.evidence_config import EvidenceSettings, evidence_settings_from_environment


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
    app.include_router(health_router)
    app.include_router(compensation_router)
    app.include_router(candidate_evidence_router)

    @app.exception_handler(RequestValidationError)
    async def invalid_request_handler(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "INVALID_REQUEST"})

    return app


app = create_app()
