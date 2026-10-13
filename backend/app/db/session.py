from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.db.base import Base


def create_database_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().pgvector_database_url
    options = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **options)


engine = create_database_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def initialize_database(database_engine: Engine = engine) -> None:
    if database_engine.dialect.name == "postgresql":
        with database_engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS insurance"))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(database_engine)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
