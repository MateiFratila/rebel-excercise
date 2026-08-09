from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError

from rebel_dot.api.authentication import get_session, require_allowed_origin
from rebel_dot.api.errors import APIError
from rebel_dot.api.schemas import AskQuestionRequest, AskQuestionResponse
from rebel_dot.core import Settings
from rebel_dot.core.observability import (
    GUARDRAIL_EVENTS,
    PROVIDER_REQUESTS,
    QUESTION_ROUTES,
    RETRIEVAL_SIMILARITY,
    logger,
    request_id,
)
from rebel_dot.domain import (
    AIProviderError,
    EmbeddingProviderError,
    ErrorCode,
    GuardrailRejectedError,
    OutputRejectedError,
    ProviderFailureKind,
)
from rebel_dot.ports import QuestionAnswerer

router = APIRouter(
    prefix="/ask-question",
    tags=["questions"],
    dependencies=[Depends(get_session), Depends(require_allowed_origin)],
)


def get_question_answerer(request: Request) -> QuestionAnswerer:
    return cast(QuestionAnswerer, request.app.state.question_answerer)


@router.post("", response_model=AskQuestionResponse)
async def ask_question(
    payload: AskQuestionRequest,
    request: Request,
    response: Response,
    answerer: Annotated[QuestionAnswerer, Depends(get_question_answerer)],
) -> AskQuestionResponse:
    resolved_request_id = request_id(request)
    try:
        answer = await answerer.ask(payload.user_question)
    except GuardrailRejectedError as error:
        GUARDRAIL_EVENTS.labels("input", "blocked", error.reason.value).inc()
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_ERROR,
            "Question was rejected by input policy",
        ) from error
    except OutputRejectedError as error:
        GUARDRAIL_EVENTS.labels("output", "blocked", error.reason.value).inc()
        raise APIError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.UPSTREAM_INVALID_RESPONSE,
            "Answer provider returned an invalid response",
        ) from error
    except AIProviderError as error:
        PROVIDER_REQUESTS.labels("openai", "question_workflow", error.kind.value).inc()
        raise _provider_api_error(error.kind) from error
    except (EmbeddingProviderError, SQLAlchemyError) as error:
        raise APIError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "A required service is temporarily unavailable",
        ) from error

    response.headers["X-Request-ID"] = resolved_request_id
    QUESTION_ROUTES.labels(answer.source.value).inc()
    GUARDRAIL_EVENTS.labels("output", "allowed", "none").inc()
    if answer.top_similarity is not None:
        RETRIEVAL_SIMILARITY.observe(answer.top_similarity)
    settings = cast(Settings, request.app.state.settings)
    logger.info(
        "question_answered",
        source=answer.source.value,
        top_similarity=answer.top_similarity,
        collection_version=answer.collection_version,
        embedding_model=answer.embedding_model or settings.embedding_model,
        chat_model=settings.chat_model,
    )
    return AskQuestionResponse(
        source=answer.source,
        matched_question=answer.matched_question,
        answer=answer.answer,
    )


def _provider_api_error(kind: ProviderFailureKind) -> APIError:
    if kind is ProviderFailureKind.RATE_LIMITED:
        return APIError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            ErrorCode.RATE_LIMITED,
            "Answer provider rate limit exceeded",
        )
    if kind is ProviderFailureKind.TIMEOUT:
        return APIError(
            status.HTTP_504_GATEWAY_TIMEOUT,
            ErrorCode.UPSTREAM_TIMEOUT,
            "Answer provider timed out",
        )
    if kind is ProviderFailureKind.INVALID_RESPONSE:
        return APIError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.UPSTREAM_INVALID_RESPONSE,
            "Answer provider returned an invalid response",
        )
    return APIError(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        "Answer provider is temporarily unavailable",
    )
