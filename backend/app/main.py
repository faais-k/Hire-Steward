import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.app.api.routes.compensation import router as compensation_router
from backend.app.api.routes.health import router as health_router
from backend.app.db.session import make_session_factory


def create_app(
    *,
    database_url: str | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> FastAPI:
    resolved_database_url = database_url or os.getenv("DATABASE_URL")
    app = FastAPI(title="JobPilot API", version="0.1.0")
    app.state.session_factory = (
        session_factory
        if session_factory is not None
        else make_session_factory(resolved_database_url)
        if resolved_database_url
        else None
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "[::1]"],
    )
    app.include_router(health_router)
    app.include_router(compensation_router)

    @app.exception_handler(RequestValidationError)
    async def invalid_request_handler(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "INVALID_REQUEST"})

    return app


app = create_app()
