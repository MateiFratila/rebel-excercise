from enum import StrEnum

from rebel_dot.domain.models import GuardrailReason


class OptimisticConcurrencyError(Exception):
    pass


class EmbeddingProviderError(Exception):
    pass


class ProviderFailureKind(StrEnum):
    INVALID_RESPONSE = "invalid_response"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


class AIProviderError(Exception):
    def __init__(self, kind: ProviderFailureKind) -> None:
        super().__init__(f"AI provider failure: {kind.value}")
        self.kind = kind


class GuardrailRejectedError(Exception):
    def __init__(self, reason: GuardrailReason) -> None:
        super().__init__(f"question rejected: {reason.value}")
        self.reason = reason


class OutputRejectedError(Exception):
    def __init__(self, reason: GuardrailReason) -> None:
        super().__init__(f"answer rejected: {reason.value}")
        self.reason = reason
