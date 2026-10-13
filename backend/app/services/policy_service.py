import hashlib
import logging
import re
import zipfile
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models.policy import PolicyChunk, PolicyDocument
from backend.app.schemas.policy import (
    DashboardStats,
    PolicyList,
    PolicySummary,
    SearchFilters,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from backend.app.services.document_processing import extract_document, section_aware_chunks
from backend.app.services.embedding import embed_texts

logger = logging.getLogger(__name__)
ALLOWED_FILE_TYPES = {"pdf", "docx"}
DEFAULT_CATEGORY = "Other"


class PolicyInputError(ValueError):
    pass


def _validate_file(data: bytes, filename: str | None) -> tuple[str, str]:
    safe_filename = Path(filename or "").name.strip()
    suffix = Path(safe_filename).suffix.lower().lstrip(".")
    if suffix not in ALLOWED_FILE_TYPES:
        raise PolicyInputError("Upload a PDF or DOCX policy document.")
    if suffix == "pdf" and not data.startswith(b"%PDF-"):
        raise PolicyInputError("The uploaded file does not have a valid PDF signature.")
    if suffix == "docx":
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                if "word/document.xml" not in archive.namelist():
                    raise PolicyInputError("The DOCX file is missing its main document.")
        except zipfile.BadZipFile as error:
            raise PolicyInputError("The uploaded file is not a valid DOCX document.") from error
    if not data:
        raise PolicyInputError("The uploaded document is empty.")
    return safe_filename, suffix


def _safe_metadata(value: str | None, default: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", value or "").strip()
    return (normalized or default)[:limit]


def ingest_policy(
    session: Session,
    *,
    data: bytes,
    filename: str | None,
    name: str | None = None,
    category: str | None = None,
    carrier: str | None = None,
    effective_date: date | None = None,
    expires_date: date | None = None,
) -> PolicyDocument:
    settings = get_settings()
    if len(data) > settings.max_upload_bytes:
        raise PolicyInputError(
            f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB upload limit."
        )
    safe_filename, file_type = _validate_file(data, filename)
    if effective_date and expires_date and expires_date < effective_date:
        raise PolicyInputError("expires_date must not be earlier than effective_date.")

    digest = hashlib.sha256(data).hexdigest()
    policy_name = _safe_metadata(
        name,
        Path(safe_filename).stem.replace("_", " ").title(),
        300,
    )
    policy_category = _safe_metadata(category, DEFAULT_CATEGORY, 100)
    policy_carrier = _safe_metadata(carrier, "", 200) or None
    series_identity = "\x1f".join(
        (
            policy_name.casefold(),
            policy_category.casefold(),
            (policy_carrier or "").casefold(),
        )
    )
    policy_series_id = hashlib.sha256(series_identity.encode("utf-8")).hexdigest()
    latest_version = session.scalar(
        select(func.max(PolicyDocument.version)).where(
            PolicyDocument.policy_series_id == policy_series_id
        )
    )
    version = (latest_version or 0) + 1
    policy_id = str(uuid4())
    settings.upload_directory.mkdir(parents=True, exist_ok=True)
    storage_path = settings.upload_directory / f"{policy_id}.{file_type}"
    storage_path.write_bytes(data)
    policy = PolicyDocument(
        id=policy_id,
        policy_series_id=policy_series_id,
        version=version,
        name=policy_name,
        filename=safe_filename,
        file_type=file_type,
        storage_path=str(storage_path),
        sha256=digest,
        category=policy_category,
        carrier=policy_carrier,
        effective_date=effective_date,
        expires_date=expires_date,
        status="active",
        ingestion_status="processing",
    )
    session.add(policy)
    session.commit()
    session.refresh(policy)

    try:
        segments = extract_document(data, file_type)
        if not segments:
            raise PolicyInputError(
                "No selectable text was found. Scanned/image-only PDFs need OCR before ingestion."
            )
        chunks = section_aware_chunks(
            segments,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        if not chunks:
            raise PolicyInputError("No searchable text chunks could be created from this document.")
        vectors: list[list[float]] = []
        for offset in range(0, len(chunks), 64):
            vectors.extend(embed_texts([chunk.content for chunk in chunks[offset : offset + 64]]))
        if len(vectors) != len(chunks):
            raise RuntimeError("Embedding count did not match the number of policy chunks.")
        session.add_all(
            [
                PolicyChunk(
                    policy_id=policy.id,
                    chunk_index=chunk.chunk_index,
                    section=chunk.section,
                    page_number=chunk.page_number,
                    content=chunk.content,
                    embedding=vector,
                    embedding_model=settings.openai_embedding_model,
                )
                for chunk, vector in zip(chunks, vectors)
            ]
        )
        policy.ingestion_status = "ready"
        policy.chunk_count = len(chunks)
        policy.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(policy)
        return policy
    except Exception:
        session.rollback()
        failed_policy = session.get(PolicyDocument, policy_id)
        if failed_policy is not None:
            failed_policy.ingestion_status = "failed"
            failed_policy.updated_at = datetime.now(timezone.utc)
            session.commit()
        logger.exception("Policy ingestion failed for policy_id=%s", policy_id)
        raise


def list_policies(
    session: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    category: str | None = None,
    status: str | None = None,
    carrier: str | None = None,
    search: str | None = None,
) -> PolicyList:
    statement = select(PolicyDocument)
    today = date.today()
    if category:
        statement = statement.where(PolicyDocument.category == category)
    if status == "archived":
        statement = statement.where(PolicyDocument.status == "archived")
    elif status == "expired":
        statement = statement.where(
            PolicyDocument.status == "active",
            PolicyDocument.expires_date < today,
        )
    elif status == "upcoming":
        statement = statement.where(
            PolicyDocument.status == "active",
            PolicyDocument.effective_date > today,
        )
    elif status == "active":
        statement = statement.where(
            PolicyDocument.status == "active",
            (PolicyDocument.effective_date.is_(None))
            | (PolicyDocument.effective_date <= today),
            (PolicyDocument.expires_date.is_(None))
            | (PolicyDocument.expires_date >= today),
        )
    if carrier:
        statement = statement.where(PolicyDocument.carrier == carrier)
    if search:
        term = f"%{search.strip()}%"
        statement = statement.where(
            PolicyDocument.name.ilike(term)
            | PolicyDocument.filename.ilike(term)
            | PolicyDocument.carrier.ilike(term)
        )
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    policies = session.scalars(
        statement.order_by(PolicyDocument.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PolicyList(
        items=[PolicySummary.model_validate(policy) for policy in policies],
        total=total,
        page=page,
        page_size=page_size,
    )


def _apply_search_filters(statement, filters: SearchFilters):
    statement = statement.where(PolicyDocument.ingestion_status == "ready")
    requested_status = filters.status or "active"
    today = date.today()
    if requested_status == "archived":
        statement = statement.where(PolicyDocument.status == "archived")
    elif requested_status == "expired":
        statement = statement.where(
            PolicyDocument.status == "active",
            PolicyDocument.expires_date < today,
        )
    elif requested_status == "upcoming":
        statement = statement.where(
            PolicyDocument.status == "active",
            PolicyDocument.effective_date > today,
        )
    else:
        statement = statement.where(
            PolicyDocument.status == "active",
            (PolicyDocument.effective_date.is_(None))
            | (PolicyDocument.effective_date <= today),
            (PolicyDocument.expires_date.is_(None))
            | (PolicyDocument.expires_date >= today),
        )
    if filters.category:
        statement = statement.where(PolicyDocument.category == filters.category)
    if filters.carrier:
        statement = statement.where(PolicyDocument.carrier == filters.carrier)
    if filters.policy_id:
        statement = statement.where(PolicyDocument.id == filters.policy_id)
    return statement


def search_policies(
    session: Session,
    request: SearchRequest,
    filters: SearchFilters | None = None,
) -> SearchResponse:
    active_filters = filters or request.filters
    candidate_count = select(func.count()).select_from(PolicyChunk).join(
        PolicyDocument,
        PolicyChunk.policy_id == PolicyDocument.id,
    )
    candidate_count = _apply_search_filters(candidate_count, active_filters)
    if not session.scalar(candidate_count):
        return SearchResponse(query=request.query, results=[], total=0)

    vectors = embed_texts([request.query])
    query_embedding = vectors[0]

    if session.bind is not None and session.bind.dialect.name == "postgresql":
        distance = PolicyChunk.embedding.cosine_distance(query_embedding)
        statement = (
            select(PolicyChunk, PolicyDocument, distance.label("distance"))
            .join(PolicyDocument, PolicyChunk.policy_id == PolicyDocument.id)
        )
        statement = _apply_search_filters(statement, active_filters)
        ranked = session.execute(statement.order_by(distance).limit(request.top_k)).all()
        results = [
            SearchResult(
                chunk_id=chunk.id,
                document_id=policy.id,
                policy_name=policy.name,
                filename=policy.filename,
                category=policy.category,
                carrier=policy.carrier,
                section=chunk.section,
                page_number=chunk.page_number,
                content=chunk.content,
                similarity_score=max(-1.0, min(1.0, 1.0 - float(distance_value))),
            )
            for chunk, policy, distance_value in ranked
        ]
    else:
        statement = (
            select(PolicyChunk, PolicyDocument)
            .join(PolicyDocument, PolicyChunk.policy_id == PolicyDocument.id)
        )
        statement = _apply_search_filters(statement, active_filters)
        candidates = session.execute(statement).all()
        scored: list[tuple[float, PolicyChunk, PolicyDocument]] = []
        query_norm = sum(value * value for value in query_embedding) ** 0.5
        for chunk, policy in candidates:
            stored = chunk.embedding
            if isinstance(stored, str):
                import json

                stored = json.loads(stored)
            if len(stored) != len(query_embedding):
                logger.warning("Skipping chunk with incompatible embedding dimensions: %s", chunk.id)
                continue
            stored_norm = sum(value * value for value in stored) ** 0.5
            if not stored_norm or not query_norm:
                similarity = 0.0
            else:
                similarity = sum(
                    left * right for left, right in zip(query_embedding, stored)
                ) / (query_norm * stored_norm)
            scored.append((similarity, chunk, policy))
        scored.sort(key=lambda item: item[0], reverse=True)
        results = [
            SearchResult(
                chunk_id=chunk.id,
                document_id=policy.id,
                policy_name=policy.name,
                filename=policy.filename,
                category=policy.category,
                carrier=policy.carrier,
                section=chunk.section,
                page_number=chunk.page_number,
                content=chunk.content,
                similarity_score=max(-1.0, min(1.0, float(score))),
            )
            for score, chunk, policy in scored[: request.top_k]
        ]
    return SearchResponse(query=request.query, results=results, total=len(results))


def dashboard_stats(session: Session) -> DashboardStats:
    total = session.scalar(select(func.count()).select_from(PolicyDocument)) or 0
    indexed = session.scalar(
        select(func.count()).select_from(PolicyDocument).where(
            PolicyDocument.ingestion_status == "ready",
            PolicyDocument.status == "active",
            (PolicyDocument.effective_date.is_(None))
            | (PolicyDocument.effective_date <= date.today()),
            (PolicyDocument.expires_date.is_(None))
            | (PolicyDocument.expires_date >= date.today()),
        )
    ) or 0
    processing = session.scalar(
        select(func.count()).select_from(PolicyDocument).where(
            PolicyDocument.ingestion_status == "processing"
        )
    ) or 0
    failed = session.scalar(
        select(func.count()).select_from(PolicyDocument).where(
            PolicyDocument.ingestion_status == "failed"
        )
    ) or 0
    chunks = session.scalar(select(func.count()).select_from(PolicyChunk)) or 0
    category_rows = session.execute(
        select(PolicyDocument.category, func.count())
        .where(PolicyDocument.status == "active")
        .group_by(PolicyDocument.category)
        .order_by(func.count().desc())
    ).all()
    return DashboardStats(
        policies=total,
        indexed_policies=indexed,
        processing_policies=processing,
        failed_policies=failed,
        chunks=chunks,
        categories=[{"name": category, "count": count} for category, count in category_rows],
    )
