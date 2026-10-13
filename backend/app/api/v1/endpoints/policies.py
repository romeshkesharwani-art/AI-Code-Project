import logging
import re
from datetime import date
from hashlib import sha256
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.config import PROJECT_ROOT
from backend.app.db.session import get_session
from backend.app.models.policy import PolicyDocument
from backend.app.schemas.policy import DashboardStats, PolicyList, PolicySummary
from backend.app.services.embedding import EmbeddingConfigurationError
from backend.app.services.policy_service import (
    PolicyInputError,
    dashboard_stats,
    ingest_policy,
    list_policies,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("", response_model=PolicyList)
def get_policies(
    category: str | None = None,
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern="^(active|archived|expired|upcoming)$",
    ),
    carrier: str | None = None,
    search: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> PolicyList:
    return list_policies(
        session,
        page=page,
        page_size=page_size,
        category=category,
        status=status_filter,
        carrier=carrier,
        search=search,
    )


@router.get("/dashboard/stats", response_model=DashboardStats)
def get_dashboard_stats(session: Session = Depends(get_session)) -> DashboardStats:
    try:
        return dashboard_stats(session)
    except SQLAlchemyError as error:
        logger.exception("Could not load policy dashboard statistics")
        raise HTTPException(status_code=503, detail="Policy database is unavailable.") from error


@router.post("/upload", response_model=PolicySummary, status_code=status.HTTP_201_CREATED)
async def upload_policy(
    file: UploadFile = File(...),
    name: str | None = Form(default=None, max_length=300),
    category: str | None = Form(default=None, max_length=100),
    carrier: str | None = Form(default=None, max_length=200),
    effective_date: date | None = Form(default=None),
    expires_date: date | None = Form(default=None),
    session: Session = Depends(get_session),
) -> PolicySummary:
    data = await file.read(get_settings().max_upload_bytes + 1)
    try:
        policy = ingest_policy(
            session,
            data=data,
            filename=file.filename,
            name=name,
            category=category,
            carrier=carrier,
            effective_date=effective_date,
            expires_date=expires_date,
        )
    except PolicyInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except EmbeddingConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Unable to ingest uploaded policy filename=%s", file.filename)
        raise HTTPException(
            status_code=502,
            detail=(
                "The policy was stored but could not be fully indexed. "
                "Check the ingestion status and server logs."
            ),
        ) from error
    finally:
        await file.close()
    return PolicySummary.model_validate(policy)


@router.post("/ingest-sources")
def ingest_bundled_sources(session: Session = Depends(get_session)) -> dict[str, object]:
    source_directory = PROJECT_ROOT / "rag"
    files = sorted(
        path
        for path in source_directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".pdf", ".docx"}
    ) if source_directory.is_dir() else []
    if not files:
        raise HTTPException(
            status_code=404,
            detail="No supported source documents were found in the project rag/ folder.",
        )
    ingested: list[str] = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []
    for path in files:
        data = path.read_bytes()
        digest = sha256(data).hexdigest()
        existing = session.scalar(
            select(PolicyDocument.id).where(
                PolicyDocument.sha256 == digest,
                PolicyDocument.ingestion_status == "ready",
            )
        )
        if existing:
            skipped.append(path.name)
            continue
        try:
            policy = ingest_policy(
                session,
                data=data,
                filename=path.name,
                category=_category_from_filename(path.stem),
            )
            ingested.append(policy.id)
        except Exception as error:
            logger.exception("Unable to ingest bundled source file=%s", path.name)
            message = str(error) if isinstance(error, PolicyInputError) else (
                "The document could not be indexed. Check the API server logs."
            )
            failed.append({"filename": path.name, "error": message})
    return {
        "discovered": len(files),
        "ingested": len(ingested),
        "skipped": len(skipped),
        "failed": len(failed),
        "ingested_policy_ids": ingested,
        "skipped_files": skipped,
        "failed_files": failed,
    }


def _category_from_filename(stem: str) -> str:
    category = re.sub(r"^\d+_", "", stem).replace("_", " ").strip().title()
    return category or "Other"


@router.get("/{policy_id}", response_model=PolicySummary)
def get_policy(policy_id: str, session: Session = Depends(get_session)) -> PolicySummary:
    policy = session.get(PolicyDocument, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy document not found.")
    return PolicySummary.model_validate(policy)


@router.get("/{policy_id}/file")
def download_policy(policy_id: str, session: Session = Depends(get_session)) -> FileResponse:
    policy = session.get(PolicyDocument, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy document not found.")
    path = Path(policy.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Stored policy file is unavailable.")
    return FileResponse(path, filename=policy.filename, media_type="application/octet-stream")


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_policy(policy_id: str, session: Session = Depends(get_session)) -> None:
    policy = session.scalar(
        select(PolicyDocument).where(PolicyDocument.id == policy_id)
    )
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy document not found.")
    policy.status = "archived"
    session.commit()
