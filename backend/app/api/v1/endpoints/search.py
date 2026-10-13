import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.session import get_session
from backend.app.schemas.policy import (
    AnswerResponse,
    EvaluationRequest,
    SearchFilters,
    SearchRequest,
    SearchResponse,
)
from backend.app.services.answer_service import AnswerConfigurationError, generate_answer
from backend.app.services.embedding import EmbeddingConfigurationError
from backend.app.services.policy_service import search_policies

logger = logging.getLogger(__name__)
router = APIRouter(tags=["search and answers"])


def _search(session: Session, request: SearchRequest) -> SearchResponse:
    try:
        return search_policies(session, request)
    except EmbeddingConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except SQLAlchemyError as error:
        logger.exception("Policy search database operation failed")
        raise HTTPException(status_code=503, detail="Policy search database is unavailable.") from error


@router.get("/search", response_model=SearchResponse)
def search_get(
    query: str = Query(min_length=2, max_length=2000),
    top_k: int = Query(default=5, ge=1, le=10),
    category: str | None = None,
    carrier: str | None = None,
    policy_id: str | None = None,
    status: str | None = Query(
        default=None,
        pattern="^(active|archived|expired|upcoming)$",
    ),
    session: Session = Depends(get_session),
) -> SearchResponse:
    request = SearchRequest(
        query=query,
        top_k=top_k,
        filters=SearchFilters(
            category=category,
            carrier=carrier,
            policy_id=policy_id,
            status=status,
        ),
    )
    return _search(session, request)


@router.post("/search", response_model=SearchResponse)
def search_post(
    request: SearchRequest,
    session: Session = Depends(get_session),
) -> SearchResponse:
    return _search(session, request)


@router.post("/answer", response_model=AnswerResponse)
def answer_question(
    request: SearchRequest,
    session: Session = Depends(get_session),
) -> AnswerResponse:
    retrieval = _search(session, request)
    try:
        answer, abstained = generate_answer(request, retrieval)
    except AnswerConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Grounded answer generation failed")
        raise HTTPException(
            status_code=502,
            detail="The answer provider could not complete the request.",
        ) from error
    return AnswerResponse(
        query=request.query,
        answer=answer,
        abstained=abstained,
        sources=retrieval.results,
    )


@router.post("/evaluate")
def evaluate_configuration(payload: EvaluationRequest, session: Session = Depends(get_session)):
    config = payload.config
    top_k_value = config.get("top_k", 5)
    if isinstance(top_k_value, bool) or not isinstance(top_k_value, int) or not 1 <= top_k_value <= 10:
        raise HTTPException(status_code=422, detail="config.top_k must be an integer from 1 to 10.")

    settings = get_settings()
    embedding_model = config.get("embedding_model")
    if embedding_model and embedding_model != settings.openai_embedding_model:
        raise HTTPException(
            status_code=422,
            detail=(
                "The requested embedding model is not indexed. Re-embed the policy documents "
                "before evaluating a different embedding model."
            ),
        )
    retriever = config.get("retriever")
    if retriever and retriever not in {"pgvector cosine", "Exact cosine", "exact cosine"}:
        raise HTTPException(
            status_code=422,
            detail="This deployment currently supports exact pgvector cosine retrieval only.",
        )
    model = config.get("model")
    prompt_instructions = config.get("prompt")
    if model is not None and (not isinstance(model, str) or len(model) > 100):
        raise HTTPException(status_code=422, detail="config.model must be a string of at most 100 characters.")
    if prompt_instructions is not None and (
        not isinstance(prompt_instructions, str) or len(prompt_instructions) > 4000
    ):
        raise HTTPException(
            status_code=422,
            detail="config.prompt must be a string of at most 4000 characters.",
        )

    request = SearchRequest(query=payload.question, top_k=top_k_value)
    retrieval = _search(session, request)
    try:
        answer, abstained = generate_answer(
            request,
            retrieval,
            model=model,
            prompt_instructions=prompt_instructions,
        )
    except AnswerConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("A/B evaluation answer generation failed")
        raise HTTPException(
            status_code=502,
            detail="The answer provider could not complete the evaluation request.",
        ) from error
    return {
        "answer": answer,
        "abstained": abstained,
        "retrieved_documents": [
            {
                "id": result.document_id,
                "document_id": result.document_id,
                "policy_id": result.document_id,
                "chunk_id": result.chunk_id,
                "filename": result.filename,
                "text": result.content,
                "content": result.content,
                "score": result.similarity_score,
            }
            for result in retrieval.results
        ],
        "retrieved_contexts": [result.content for result in retrieval.results],
    }
