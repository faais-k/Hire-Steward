from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_session
from backend.app.db import models
from backend.app.domain.compensation import validate_money
from backend.app.services.preferences import get_minimum_compensation


router = APIRouter()

_REQUIRED_TABLE_COLUMNS = {
    table.name: frozenset(column.name for column in table.columns)
    for table in models.Base.metadata.sorted_tables
}
_REQUIRED_TABLE_COLUMNS["alembic_version"] = frozenset({"version_num"})


@lru_cache(maxsize=1)
def expected_migration_heads() -> frozenset[str]:
    alembic_ini = Path(__file__).resolve().parents[3] / "alembic.ini"
    config = Config(str(alembic_ini))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


def _verify_required_schema(session: Session) -> None:
    inspector = inspect(session.connection())
    actual_tables = set(inspector.get_table_names())
    if not _REQUIRED_TABLE_COLUMNS.keys() <= actual_tables:
        raise RuntimeError("required database schema is incomplete")

    for table_name, expected_columns in _REQUIRED_TABLE_COLUMNS.items():
        actual_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        if not expected_columns <= actual_columns:
            raise RuntimeError("required database schema is incomplete")


def _verify_preference(preference: models.CompensationPreference) -> None:
    amount = preference.amount
    try:
        normalized_amount = validate_money(amount, field_name="minimum compensation")
    except ValueError as exc:
        raise RuntimeError("compensation preference is invalid") from exc

    if (
        preference.id != 1
        or amount != normalized_amount
        or preference.currency != "INR"
        or preference.period != "YEAR"
        or type(preference.version) is not int
        or preference.version < 1
    ):
        raise RuntimeError("compensation preference is invalid")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
        _verify_required_schema(session)
        applied_heads = frozenset(
            session.scalars(text("SELECT version_num FROM alembic_version")).all()
        )
        if not applied_heads or applied_heads != expected_migration_heads():
            raise RuntimeError("database migrations are not current")
        _verify_preference(get_minimum_compensation(session))
    except (SQLAlchemyError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="DATABASE_NOT_READY") from exc
    return {"status": "ready"}
