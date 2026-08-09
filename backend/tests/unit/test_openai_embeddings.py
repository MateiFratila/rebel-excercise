from typing import cast

import pytest
from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from rebel_dot.adapters.openai_embeddings import OpenAIEmbeddingProvider
from rebel_dot.domain import EmbeddingProviderError


class FakeOpenAIEmbeddings:
    def __init__(self, result: list[list[float]] | Exception) -> None:
        self.result = result
        self.calls: list[list[str]] = []

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def make_provider(client: FakeOpenAIEmbeddings) -> OpenAIEmbeddingProvider:
    return OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        dimensions=3,
        api_key=SecretStr("sk-test-only"),
        timeout_seconds=1,
        max_retries=0,
        batch_size=2,
        client=cast(OpenAIEmbeddings, client),
    )


async def test_embedding_adapter_returns_validated_vectors() -> None:
    client = FakeOpenAIEmbeddings([[1, 0, 0], [0, 1, 0]])
    provider = make_provider(client)

    vectors = await provider.embed(("one", "two"))

    assert vectors == ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    assert client.calls == [["one", "two"]]
    assert await provider.embed(()) == ()


@pytest.mark.parametrize(
    "result",
    [
        [[1, 0, 0]],
        [[1, 0], [0, 1]],
        RuntimeError("secret provider detail"),
    ],
)
async def test_embedding_adapter_maps_malformed_and_provider_failures(
    result: list[list[float]] | Exception,
) -> None:
    provider = make_provider(FakeOpenAIEmbeddings(result))

    with pytest.raises(EmbeddingProviderError) as error:
        await provider.embed(("one", "two"))

    assert "secret provider detail" not in str(error.value)
