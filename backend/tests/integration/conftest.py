import os
from dataclasses import dataclass
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class PostgresDatabase:
    engine: Engine
    session_factory: sessionmaker[Session]
    schema: str


@pytest.fixture
def postgres_database():
    """Dedicated `jobpilot_test` database, one disposable schema per test."""
    database_url = os.getenv("JOBPILOT_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("JOBPILOT_TEST_DATABASE_URL is not configured")
    parsed_url = make_url(database_url)
    if parsed_url.drivername != "postgresql+psycopg":
        pytest.fail("PostgreSQL integration tests require the psycopg PostgreSQL URL")
    if parsed_url.database != "jobpilot_test":
        pytest.fail("PostgreSQL integration tests require the dedicated jobpilot_test database")

    schema = f"jobpilot_test_{uuid4().hex}"
    admin_engine = create_engine(database_url, pool_pre_ping=True)
    engine: Engine | None = None
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        created = True
        engine = create_engine(
            database_url,
            connect_args={"options": f"-csearch_path={schema}"},
            pool_pre_ping=True,
        )
        yield PostgresDatabase(
            engine=engine,
            session_factory=sessionmaker(bind=engine, expire_on_commit=False),
            schema=schema,
        )
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin_engine.dispose()


def upgrade(database: PostgresDatabase, revision: str = "head") -> None:
    config = Config("backend/alembic.ini")
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def local_headers() -> dict[str, str]:
    return {"host": "localhost", "origin": "http://localhost"}
