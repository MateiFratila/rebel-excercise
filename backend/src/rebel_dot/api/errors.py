from collections.abc import Mapping
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from rebel_dot.api.schemas import ErrorDetail, ErrorResponse
from rebel_dot.core.observability import request_id
from rebel_dot.domain import ErrorCode


@dataclass(frozen=True, slots=True)
class APIError(Exception):
    status_code: int
    code: ErrorCode
    message: str
    headers: Mapping[str, str] | None = None


def install_error_handlers(app: FastAPI) -> None:
    def error_response(
        request: Request,
        status_code: int,
        code: ErrorCode,
        message: str,
        headers: Mapping[str, str] | None = None,
    ) -> JSONResponse:
        resolved_request_id = request_id(request)
        response_headers = dict(headers or {})
        response_headers["X-Request-ID"] = resolved_request_id
        body = ErrorResponse(
            error=ErrorDetail(
                code=code,
                message=message,
                request_id=resolved_request_id,
            )
        )
        return JSONResponse(
            status_code=status_code,
            content=body.model_dump(mode="json"),
            headers=response_headers,
        )

    @app.exception_handler(APIError)
    async def handle_api_error(request: Request, error: APIError) -> JSONResponse:
        return error_response(
            request,
            error.status_code,
            error.code,
            error.message,
            error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        return error_response(
            request,
            422,
            ErrorCode.VALIDATION_ERROR,
            "Request validation failed",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _error: Exception) -> JSONResponse:
        return error_response(
            request,
            500,
            ErrorCode.INTERNAL_ERROR,
            "Internal server error",
        )
