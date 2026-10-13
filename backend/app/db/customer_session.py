from collections.abc import Generator
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.models.customer import Customer  # Register customer table metadata.


class CustomerDatabaseConfigurationError(RuntimeError):
    pass


@lru_cache
def get_customer_engine() -> Engine:
    database_url = get_settings().customer_database_url.strip()
    if not database_url:
        raise CustomerDatabaseConfigurationError(
            "Set CUSTOMER_DATABASE_URL in .env to enable customer data storage."
        )
    if not database_url.startswith("postgresql+psycopg://"):
        raise CustomerDatabaseConfigurationError(
            "CUSTOMER_DATABASE_URL must use a PostgreSQL psycopg URL."
        )
    return create_engine(database_url, pool_pre_ping=True)


def initialize_customer_database() -> bool:
    if not get_settings().customer_database_url.strip():
        return False
    Customer.__table__.create(get_customer_engine(), checkfirst=True)
    return True


def get_customer_session() -> Generator[Session, None, None]:
    try:
        engine = get_customer_engine()
    except CustomerDatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_factory() as session:
        yield session
