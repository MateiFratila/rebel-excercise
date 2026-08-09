from typing import Annotated, cast
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError

from rebel_dot.api.authentication import get_session, require_allowed_origin
from rebel_dot.api.errors import APIError
from rebel_dot.api.schemas import AskQuestionRequest, AskQuestionResponse
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
logger = structlog.get_logger()


def get_question_answerer(request: Request) -> QuestionAnswerer:
    return cast(QuestionAnswerer, request.app.state.question_answerer)


@router.post("", response_model=AskQuestionResponse)
async def ask_question(
    payload: AskQuestionRequest,
    response: Response,
    answerer: Annotated[QuestionAnswerer, Depends(get_question_answerer)],
) -> AskQuestionResponse:
    request_id = str(uuid4())
    try:
        answer = await answerer.ask(payload.user_question)
    except GuardrailRejectedError as error:
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_ERROR,
            "Question was rejected by input policy",
        ) from error
    except OutputRejectedError as error:
        raise APIError(
            status.HTTP_502_BAD_GATEWAY,
            ErrorCode.UPSTREAM_INVALID_RESPONSE,
            "Answer provider returned an invalid response",
        ) from error
    except AIProviderError as error:
        raise _provider_api_error(error.kind) from error
    except (EmbeddingProviderError, SQLAlchemyError) as error:
        raise APIError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "A required service is temporarily unavailable",
        ) from error

    response.headers["X-Request-ID"] = request_id
    logger.info("question_answered", request_id=request_id, source=answer.source.value)
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
