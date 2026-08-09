from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response, status

from rebel_dot.api.errors import APIError
from rebel_dot.api.schemas import CreateSessionRequest
from rebel_dot.application.authentication import (
    InvalidCredentialsError,
    LoginRateLimitedError,
    SessionService,
)
from rebel_dot.core import Settings
from rebel_dot.domain import AuthSession, ErrorCode

router = APIRouter(prefix="/auth/session", tags=["authentication"])


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_session_service(request: Request) -> SessionService:
    return cast(SessionService, request.app.state.session_service)


def require_allowed_origin(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if request.headers.get("origin") not in settings.allowed_origins:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code=ErrorCode.FORBIDDEN,
            message="Request origin is not allowed",
        )


async def get_session(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[SessionService, Depends(get_session_service)],
) -> AuthSession:
    token = request.cookies.get(settings.session_cookie_name)
    if token is None:
        raise _authentication_required()

    session = await service.resolve_session(token)
    if session is None:
        raise _authentication_required()
    return session


@router.post(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_allowed_origin)],
)
async def create_session(
    payload: CreateSessionRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[SessionService, Depends(get_session_service)],
) -> None:
    client_id = request.client.host if request.client is not None else "unknown"
    try:
        created = await service.create_session(payload.password, client_id)
    except InvalidCredentialsError as error:
        raise APIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=ErrorCode.AUTHENTICATION_REQUIRED,
            message="Authentication failed",
        ) from error
    except LoginRateLimitedError as error:
        raise APIError(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code=ErrorCode.RATE_LIMITED,
            message="Too many login attempts",
            headers={"Retry-After": str(settings.login_rate_window_seconds)},
        ) from error

    response.set_cookie(
        key=settings.session_cookie_name,
        value=created.token,
        max_age=settings.session_lifetime_seconds,
        expires=created.expires_at,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
    )


@router.get("", status_code=status.HTTP_204_NO_CONTENT)
async def session_status(_session: Annotated[AuthSession, Depends(get_session)]) -> None:
    return None


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_allowed_origin)],
)
async def delete_session(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[SessionService, Depends(get_session_service)],
) -> None:
    token = request.cookies.get(settings.session_cookie_name)
    if token is not None:
        await service.revoke_session(token)
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _authentication_required() -> APIError:
    return APIError(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code=ErrorCode.AUTHENTICATION_REQUIRED,
        message="Authentication required",
    )
