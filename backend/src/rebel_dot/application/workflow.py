from collections.abc import Mapping
from typing import Protocol, cast

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from rebel_dot.domain import (
    AnswerSource,
    GuardrailRejectedError,
    GuardrailResult,
    OutputRejectedError,
    QuestionAnswer,
    RetrievalCandidate,
    Route,
    RoutingEvidence,
    ScopeDecision,
    ScopeResult,
    WorkflowState,
)
from rebel_dot.domain.content import normalize_question
from rebel_dot.ports import (
    ChatProvider,
    FAQRetriever,
    QuestionGuardrail,
    RoutingPolicy,
    ScopeClassifier,
)

COMPLIANCE_ANSWER = (
    "This is not really what I was trained for, therefore I cannot answer. Try again."
)


class OutputGuardrail(Protocol):
    def evaluate(self, answer: str) -> GuardrailResult: ...


class QuestionAnsweringService:
    def __init__(
        self,
        *,
        question_guardrail: QuestionGuardrail,
        output_guardrail: OutputGuardrail,
        scope_classifier: ScopeClassifier,
        retriever: FAQRetriever,
        routing_policy: RoutingPolicy,
        chat_provider: ChatProvider,
        scope_confidence_threshold: float,
    ) -> None:
        self._question_guardrail = question_guardrail
        self._output_guardrail = output_guardrail
        self._scope_classifier = scope_classifier
        self._retriever = retriever
        self._routing_policy = routing_policy
        self._chat_provider = chat_provider
        self._scope_confidence_threshold = scope_confidence_threshold
        self._graph = self._build_graph()

    async def ask(self, question: str) -> QuestionAnswer:
        result = cast(
            Mapping[str, object], await self._graph.ainvoke(WorkflowState(raw_question=question))
        )
        state = WorkflowState(
            raw_question=cast(str, result["raw_question"]),
            normalized_question=cast(str | None, result.get("normalized_question")),
            guardrail=cast(GuardrailResult | None, result.get("guardrail")),
            scope=cast(ScopeResult | None, result.get("scope")),
            candidates=cast(tuple[RetrievalCandidate, ...], result.get("candidates", ())),
            route=cast(Route | None, result.get("route")),
            answer=cast(str | None, result.get("answer")),
            diagnostics=cast(Mapping[str, object], result.get("diagnostics", {})),
        )
        if state.route is None or state.answer is None:
            raise RuntimeError("question workflow completed without an answer")
        matched_question = state.candidates[0].question if state.route is Route.LOCAL else None
        return QuestionAnswer(
            source=AnswerSource(state.route.value),
            matched_question=matched_question,
            answer=state.answer,
        )

    def _build_graph(
        self,
    ) -> CompiledStateGraph[WorkflowState, None, WorkflowState, WorkflowState]:
        graph: StateGraph[WorkflowState, None, WorkflowState, WorkflowState] = StateGraph(
            WorkflowState
        )
        compliance_node: RunnableLambda[WorkflowState, dict[str, object]] = RunnableLambda(
            self._answer_compliance
        )
        graph.add_node("normalize", self._normalize)
        graph.add_node("guard", self._guard)
        graph.add_node("reject_input", self._reject_input)
        graph.add_node("classify", self._classify)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("select_route", self._select_route)
        graph.add_node("answer_local", self._answer_local)
        graph.add_node("answer_openai", self._answer_openai)
        graph.add_node("answer_compliance", compliance_node)
        graph.add_node("validate_output", self._validate_output)

        graph.add_edge(START, "normalize")
        graph.add_edge("normalize", "guard")
        graph.add_conditional_edges(
            "guard",
            self._after_guard,
            {"classify": "classify", "reject": "reject_input"},
        )
        graph.add_conditional_edges(
            "classify",
            self._after_classification,
            {"retrieve": "retrieve", "route": "select_route"},
        )
        graph.add_edge("retrieve", "select_route")
        graph.add_conditional_edges(
            "select_route",
            self._after_route,
            {
                Route.LOCAL: "answer_local",
                Route.OPENAI: "answer_openai",
                Route.COMPLIANCE: "answer_compliance",
                Route.ERROR: "reject_input",
            },
        )
        graph.add_edge("answer_local", "validate_output")
        graph.add_edge("answer_openai", "validate_output")
        graph.add_edge("answer_compliance", "validate_output")
        graph.add_edge("validate_output", END)
        return graph.compile()

    @staticmethod
    def _normalize(state: WorkflowState) -> dict[str, object]:
        return {"normalized_question": normalize_question(state.raw_question)}

    async def _guard(self, state: WorkflowState) -> dict[str, object]:
        question = self._normalized_question(state)
        return {"guardrail": await self._question_guardrail.evaluate(question)}

    @staticmethod
    def _after_guard(state: WorkflowState) -> str:
        return "classify" if state.guardrail is not None and state.guardrail.allowed else "reject"

    @staticmethod
    def _reject_input(state: WorkflowState) -> dict[str, object]:
        if state.guardrail is None or state.guardrail.reason is None:
            raise RuntimeError("question workflow rejected input without a reason")
        raise GuardrailRejectedError(state.guardrail.reason)

    async def _classify(self, state: WorkflowState) -> dict[str, object]:
        return {"scope": await self._scope_classifier.classify(self._normalized_question(state))}

    def _after_classification(self, state: WorkflowState) -> str:
        if state.scope is None:
            raise RuntimeError("question workflow did not classify input")
        if (
            state.scope.decision is ScopeDecision.OUT_OF_DOMAIN
            and state.scope.confidence >= self._scope_confidence_threshold
        ):
            return "route"
        return "retrieve"

    async def _retrieve(self, state: WorkflowState) -> dict[str, object]:
        candidates = await self._retriever.search(self._normalized_question(state), limit=3)
        return {"candidates": tuple(candidates)}

    def _select_route(self, state: WorkflowState) -> dict[str, object]:
        if state.guardrail is None or state.scope is None:
            raise RuntimeError("question workflow lacks routing evidence")
        route = self._routing_policy.select(
            RoutingEvidence(state.guardrail, state.scope, state.candidates)
        )
        return {"route": route}

    @staticmethod
    def _after_route(state: WorkflowState) -> Route:
        if state.route is None:
            raise RuntimeError("question workflow did not select a route")
        return state.route

    @staticmethod
    def _answer_local(state: WorkflowState) -> dict[str, object]:
        if not state.candidates:
            raise RuntimeError("local route selected without a candidate")
        return {"answer": state.candidates[0].answer}

    async def _answer_openai(self, state: WorkflowState) -> dict[str, object]:
        answer = await self._chat_provider.answer(self._normalized_question(state))
        return {"answer": answer}

    def _answer_compliance(self, _state: WorkflowState) -> dict[str, object]:
        return {"answer": COMPLIANCE_ANSWER}

    def _validate_output(self, state: WorkflowState) -> dict[str, object]:
        result = self._output_guardrail.evaluate(state.answer or "")
        if not result.allowed:
            if result.reason is None:
                raise RuntimeError("output guardrail rejected answer without a reason")
            raise OutputRejectedError(result.reason)
        return {}

    @staticmethod
    def _normalized_question(state: WorkflowState) -> str:
        if state.normalized_question is None:
            raise RuntimeError("question workflow did not normalize input")
        return state.normalized_question
