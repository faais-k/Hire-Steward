from collections.abc import Generator
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker


def get_session(request: Request) -> Generator[Session, None, None]:
    factory: sessionmaker[Session] | None = request.app.state.session_factory
    if factory is None:
        raise HTTPException(status_code=503, detail="DATABASE_NOT_CONFIGURED")
    with factory() as session:
        try:
            yield session
        except (OperationalError, ProgrammingError) as exc:
            raise HTTPException(status_code=503, detail="DATABASE_NOT_READY") from exc


def require_local_same_origin(request: Request) -> None:
    host_header = request.headers.get("host")
    origin_header = request.headers.get("origin")
    source_url = origin_header

    # For safe methods (e.g. GET /export), browsers do not send Origin by spec;
    # fall back to verifying Referer against same-origin loopback host.
    if not source_url or source_url == "null":
        if request.method in {"GET", "HEAD"}:
            source_url = request.headers.get("referer")
        if not source_url or source_url == "null" or not host_header:
            raise HTTPException(status_code=403, detail="LOCAL_SAME_ORIGIN_REQUIRED")

    if not host_header:
        raise HTTPException(status_code=403, detail="LOCAL_SAME_ORIGIN_REQUIRED")

    try:
        host = urlsplit(f"//{host_header}")
        origin = urlsplit(source_url)
        host_port = host.port
        origin_port = origin.port
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="LOCAL_SAME_ORIGIN_REQUIRED") from exc
    local_names = {"localhost", "127.0.0.1", "::1"}
    if (
        host.hostname is None
        or host.hostname.lower() not in local_names
        or origin.hostname is None
        or origin.hostname.lower() != host.hostname.lower()
        or origin.scheme not in {"http", "https"}
        or origin.username
        or origin.password
    ):
        raise HTTPException(status_code=403, detail="LOCAL_SAME_ORIGIN_REQUIRED")

    # If Origin header was provided, enforce strict empty path/query/fragment
    if origin_header and origin_header != "null":
        if origin.path not in {"", "/"} or origin.query or origin.fragment:
            raise HTTPException(status_code=403, detail="LOCAL_SAME_ORIGIN_REQUIRED")

    default_port = 443 if origin.scheme == "https" else 80
    if (host_port or default_port) != (origin_port or default_port):
        raise HTTPException(status_code=403, detail="LOCAL_SAME_ORIGIN_REQUIRED")
