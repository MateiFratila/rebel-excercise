import re
import unicodedata

from rebel_dot.domain import (
    GuardrailReason,
    GuardrailResult,
    Route,
    RoutingEvidence,
    ScopeDecision,
)

_PROMPT_INJECTION = re.compile(
    r"\b(?:ignore|disregard|override)\b.{0,40}\b(?:instructions?|prompts?|rules?)\b",
    re.IGNORECASE,
)
_SECRET_EXFILTRATION = re.compile(
    r"\b(?:reveal|show|print|repeat|leak|extract)\b.{0,60}"
    r"\b(?:system|developer|hidden|secret|api[ _-]?key|instructions?|prompts?)\b",
    re.IGNORECASE,
)
_ENCODED_PAYLOAD = re.compile(r"(?:[A-Za-z0-9+/]{160,}={0,2}|[A-Fa-f0-9]{200,})")
_SECRET_PATTERN = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")
_HIDDEN_PROMPT_DISCLOSURE = re.compile(
    r"\b(?:system|developer) (?:message|prompt) (?:says|is|was)\b",
    re.IGNORECASE,
)
_ACTION_CLAIM = re.compile(
    r"\b(?:i|we) (?:have |successfully )?(?:reset|changed|deleted|created|updated|"
    r"unlocked|disabled|enabled|refunded|cancelled|canceled) (?:your|the)\b",
    re.IGNORECASE,
)


class RuleBasedQuestionGuardrail:
    def __init__(self, max_chars: int) -> None:
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        self._max_chars = max_chars

    async def evaluate(self, question: str) -> GuardrailResult:
        if not question:
            return GuardrailResult(False, GuardrailReason.EMPTY_INPUT)
        if len(question) > self._max_chars:
            return GuardrailResult(False, GuardrailReason.INPUT_TOO_LONG)
        if any(
            unicodedata.category(character) == "Cc" and not character.isspace()
            for character in question
        ):
            return GuardrailResult(False, GuardrailReason.UNSUPPORTED_CHARACTERS)
        if _SECRET_EXFILTRATION.search(question):
            return GuardrailResult(False, GuardrailReason.SECRET_EXFILTRATION)
        if _PROMPT_INJECTION.search(question):
            return GuardrailResult(False, GuardrailReason.PROMPT_INJECTION)
        if _ENCODED_PAYLOAD.search(question):
            return GuardrailResult(False, GuardrailReason.ENCODED_PAYLOAD)
        return GuardrailResult(True)


class RuleBasedOutputGuardrail:
    def __init__(self, max_chars: int = 4000) -> None:
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        self._max_chars = max_chars

    def evaluate(self, answer: str) -> GuardrailResult:
        if not answer.strip():
            return GuardrailResult(False, GuardrailReason.EMPTY_OUTPUT)
        if len(answer) > self._max_chars:
            return GuardrailResult(False, GuardrailReason.OUTPUT_TOO_LONG)
        if _SECRET_PATTERN.search(answer):
            return GuardrailResult(False, GuardrailReason.SECRET_LEAK)
        if _HIDDEN_PROMPT_DISCLOSURE.search(answer):
            return GuardrailResult(False, GuardrailReason.HIDDEN_PROMPT_DISCLOSURE)
        if _ACTION_CLAIM.search(answer):
            return GuardrailResult(False, GuardrailReason.UNSUPPORTED_ACTION_CLAIM)
        return GuardrailResult(True)


class ConfidenceRoutingPolicy:
    def __init__(
        self,
        similarity_threshold: float,
        similarity_margin: float,
        scope_confidence_threshold: float,
    ) -> None:
        for name, value in (
            ("similarity_threshold", similarity_threshold),
            ("similarity_margin", similarity_margin),
            ("scope_confidence_threshold", scope_confidence_threshold),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one")
        self._similarity_threshold = similarity_threshold
        self._similarity_margin = similarity_margin
        self._scope_confidence_threshold = scope_confidence_threshold

    def select(self, evidence: RoutingEvidence) -> Route:
        if not evidence.guardrail.allowed:
            return Route.ERROR

        scope_is_confident = evidence.scope.confidence >= self._scope_confidence_threshold
        if evidence.scope.decision is ScopeDecision.OUT_OF_DOMAIN and scope_is_confident:
            return Route.COMPLIANCE

        has_local_match = self._has_local_match(evidence)
        if has_local_match:
            return Route.LOCAL
        if evidence.scope.decision is ScopeDecision.IN_DOMAIN and scope_is_confident:
            return Route.OPENAI
        return Route.COMPLIANCE

    def _has_local_match(self, evidence: RoutingEvidence) -> bool:
        if not evidence.candidates:
            return False
        top_score = evidence.candidates[0].similarity
        second_score = evidence.candidates[1].similarity if len(evidence.candidates) > 1 else 0.0
        return (
            top_score >= self._similarity_threshold
            and top_score - second_score >= self._similarity_margin
        )
