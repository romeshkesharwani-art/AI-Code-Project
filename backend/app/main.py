import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.api.v1.api import api_router
from backend.app.core.config import get_settings
from backend.app.db.customer_session import initialize_customer_database
from backend.app.db.session import engine, initialize_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        initialize_database()
        initialize_customer_database()
    except Exception:
        logger.exception("Database initialization failed")
        raise
    yield


app = FastAPI(
    title=settings.app_name,
    description="Insurance policy management, vector search, and grounded question answering.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
def readiness() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        logger.exception("Readiness check failed")
        raise HTTPException(status_code=503, detail="Policy database is unavailable.") from error
    return {"status": "ready"}
