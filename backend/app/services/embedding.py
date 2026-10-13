from functools import lru_cache
from typing import Any

from openai import OpenAI

from backend.app.core.config import get_settings


class EmbeddingConfigurationError(RuntimeError):
    pass


@lru_cache
def _openai_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    if not settings.openai_api_key:
        raise EmbeddingConfigurationError(
            "Set OPENAI_API_KEY in the project .env file before indexing or searching policies."
        )
    client: Any = _openai_client(settings.openai_api_key)
    response = client.embeddings.create(
        model=settings.openai_embedding_model,
        input=texts,
        dimensions=settings.embedding_dimensions,
    )
    vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
    if len(vectors) != len(texts) or any(
        len(vector) != settings.embedding_dimensions for vector in vectors
    ):
        raise RuntimeError("The embedding provider returned an unexpected vector shape.")
    return vectors
