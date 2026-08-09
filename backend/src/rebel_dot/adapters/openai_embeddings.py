from collections.abc import Sequence
from time import perf_counter

from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from rebel_dot.core.observability import logger, observe_provider
from rebel_dot.domain import EmbeddingProviderError


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        *,
        model: str,
        dimensions: int,
        api_key: SecretStr,
        timeout_seconds: float,
        max_retries: int,
        batch_size: int,
        client: OpenAIEmbeddings | None = None,
    ) -> None:
        self._dimensions = dimensions
        self._client = client or OpenAIEmbeddings(
            model=model,
            dimensions=dimensions,
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
            chunk_size=batch_size,
        )

    async def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        if not texts:
            return ()
        started_at = perf_counter()
        try:
            vectors = await self._client.aembed_documents(list(texts))
        except Exception as error:
            observe_provider("embeddings", "unavailable", started_at)
            logger.warning(
                "provider_request_failed",
                provider="openai",
                operation="embeddings",
                outcome="unavailable",
                item_count=len(texts),
            )
            raise EmbeddingProviderError("embedding provider request failed") from error

        if len(vectors) != len(texts):
            observe_provider("embeddings", "invalid_response", started_at)
            raise EmbeddingProviderError("embedding provider returned an unexpected result count")
        if any(len(vector) != self._dimensions for vector in vectors):
            observe_provider("embeddings", "invalid_response", started_at)
            raise EmbeddingProviderError("embedding provider returned incompatible dimensions")
        observe_provider("embeddings", "success", started_at)
        return tuple(tuple(float(value) for value in vector) for vector in vectors)
