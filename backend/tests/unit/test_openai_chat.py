from collections.abc import Sequence

import httpx
import pytest
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from openai import APIConnectionError, RateLimitError
from pydantic import SecretStr

from rebel_dot.adapters.openai_chat import (
    SCOPE_TAXONOMY_VERSION,
    OpenAIChatProvider,
    OpenAIScopeClassifier,
    ScopeClassification,
    SupportAnswer,
)
from rebel_dot.domain import (
    AIProviderError,
    ProviderFailureKind,
    ScopeDecision,
    ScopeResult,
)


class FakeStructuredClient[ResultT]:
    def __init__(self, result: ResultT | Exception) -> None:
        self.result = result
        self.calls: list[Sequence[BaseMessage]] = []

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> ResultT:
        self.calls.append(messages)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def classifier(client: FakeStructuredClient[ScopeClassification]) -> OpenAIScopeClassifier:
    return OpenAIScopeClassifier(
        model="gpt-5.4-mini",
        api_key=SecretStr("sk-test-only"),
        timeout_seconds=1,
        max_retries=0,
        client=client,
    )


def chat_provider(client: FakeStructuredClient[SupportAnswer]) -> OpenAIChatProvider:
    return OpenAIChatProvider(
        model="gpt-5.4-mini",
        api_key=SecretStr("sk-test-only"),
        timeout_seconds=1,
        max_retries=0,
        client=client,
    )


async def test_scope_classifier_returns_structured_result_and_isolates_user_input() -> None:
    client = FakeStructuredClient(ScopeClassification(decision="in_domain", confidence=0.93))

    result = await classifier(client).classify("My Wi-Fi keeps disconnecting")

    assert result == ScopeResult(ScopeDecision.IN_DOMAIN, 0.93)
    assert isinstance(client.calls[0][0], SystemMessage)
    assert isinstance(client.calls[0][1], HumanMessage)
    assert client.calls[0][1].content == "My Wi-Fi keeps disconnecting"
    assert "My Wi-Fi" not in str(client.calls[0][0].content)
    assert SCOPE_TAXONOMY_VERSION in str(client.calls[0][0].content)


async def test_chat_provider_returns_structured_answer() -> None:
    client = FakeStructuredClient(SupportAnswer(answer="Restart the router and retry."))

    answer = await chat_provider(client).answer("Why is my Wi-Fi offline?")

    assert answer == "Restart the router and retry."


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        (TimeoutError(), ProviderFailureKind.TIMEOUT),
        (
            RateLimitError(
                "limited",
                response=httpx.Response(429, request=httpx.Request("POST", "https://example.test")),
                body=None,
            ),
            ProviderFailureKind.RATE_LIMITED,
        ),
        (
            APIConnectionError(request=httpx.Request("POST", "https://example.test")),
            ProviderFailureKind.UNAVAILABLE,
        ),
        (RuntimeError("secret upstream detail"), ProviderFailureKind.UNAVAILABLE),
    ],
)
async def test_provider_failures_are_safely_typed(
    failure: Exception,
    kind: ProviderFailureKind,
) -> None:
    provider = chat_provider(FakeStructuredClient[SupportAnswer](failure))

    with pytest.raises(AIProviderError) as raised:
        await provider.answer("Help")

    assert raised.value.kind is kind
    assert "secret upstream detail" not in str(raised.value)


async def test_malformed_structured_result_is_rejected() -> None:
    provider = chat_provider(FakeStructuredClient[SupportAnswer](object()))  # type: ignore[arg-type]

    with pytest.raises(AIProviderError) as raised:
        await provider.answer("Help")

    assert raised.value.kind is ProviderFailureKind.INVALID_RESPONSE
