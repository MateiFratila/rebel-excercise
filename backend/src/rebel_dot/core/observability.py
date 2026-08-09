import logging
from collections.abc import Mapping, MutableMapping
from time import perf_counter
from typing import Any
from uuid import uuid4

import structlog
from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "answer",
    "api_key",
    "authorization",
    "cookie",
    "password",
    "question",
    "secret",
    "token",
)

HTTP_REQUESTS = Counter(
    "rebel_dot_http_requests_total",
    "HTTP requests handled by method, route, and status.",
    ("method", "route", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "rebel_dot_http_request_duration_seconds",
    "HTTP request duration by method and route.",
    ("method", "route"),
)
AUTH_EVENTS = Counter(
    "rebel_dot_auth_events_total",
    "Authentication outcomes.",
    ("outcome",),
)
AUTH_ACTIVE_SESSIONS = Gauge(
    "rebel_dot_auth_active_sessions",
    "Active, unexpired, and unrevoked sessions at the latest authentication operation.",
)
QUESTION_ROUTES = Counter(
    "rebel_dot_question_routes_total",
    "Question routing outcomes.",
    ("route",),
)
RETRIEVAL_SIMILARITY = Histogram(
    "rebel_dot_retrieval_top_similarity",
    "Top retrieval cosine similarity observed by the question workflow.",
    buckets=(0.5, 0.6, 0.7, 0.78, 0.82, 0.84, 0.86, 0.9, 0.95, 1.0),
)
GUARDRAIL_EVENTS = Counter(
    "rebel_dot_guardrail_events_total",
    "Input and output guardrail outcomes.",
    ("stage", "outcome", "reason"),
)
PROVIDER_REQUESTS = Counter(
    "rebel_dot_provider_requests_total",
    "Provider request outcomes by operation.",
    ("provider", "operation", "outcome"),
)
PROVIDER_DURATION = Histogram(
    "rebel_dot_provider_request_duration_seconds",
    "Provider request duration by operation.",
    ("provider", "operation"),
)
PROVIDER_TOKENS = Counter(
    "rebel_dot_provider_tokens_total",
    "Provider-reported token usage when available.",
    ("model", "direction"),
)
PROVIDER_COST = Counter(
    "rebel_dot_provider_estimated_cost_usd_total",
    "Estimated provider cost when usage and approved pricing are available.",
    ("model",),
)
EMBEDDING_JOBS = Counter(
    "rebel_dot_embedding_jobs_total",
    "Embedding job outcomes.",
    ("outcome",),
)
EMBEDDING_JOB_ITEMS = Counter(
    "rebel_dot_embedding_job_items_total",
    "Embedding job item outcomes.",
    ("outcome",),
)

logger = structlog.get_logger("rebel_dot")


def configure_observability(log_level: str) -> None:
    logging.basicConfig(level=log_level, format="%(message)s")
    structlog.configure(
        processors=(
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            redact_sensitive,
            structlog.processors.JSONRenderer(sort_keys=True),
        ),
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def redact_sensitive(
    _logger: object,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    for key, value in tuple(event_dict.items()):
        if any(part in key.lower() for part in _SENSITIVE_KEY_PARTS):
            event_dict[key] = REDACTED
        elif isinstance(value, Mapping):
            event_dict[key] = _redact_mapping(value)
        elif isinstance(value, (list, tuple)):
            event_dict[key] = [_redact_value(item) for item in value]
    return event_dict


async def observe_http_request(request: Request, call_next: Any) -> Response:
    request_id = str(uuid4())
    request.state.request_id = request_id
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    started_at = perf_counter()
    response: Response | None = None
    try:
        response = await call_next(request)
        response.headers.setdefault("X-Request-ID", request_id)
        return response
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        status_code = response.status_code if response is not None else 500
        duration = perf_counter() - started_at
        HTTP_REQUESTS.labels(request.method, route_path, str(status_code)).inc()
        HTTP_REQUEST_DURATION.labels(request.method, route_path).observe(duration)
        logger.info(
            "http_request_completed",
            method=request.method,
            route=route_path,
            status_code=status_code,
            latency_ms=round(duration * 1000, 3),
        )
        structlog.contextvars.clear_contextvars()


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", uuid4()))


def observe_provider(
    operation: str,
    outcome: str,
    started_at: float,
    *,
    provider: str = "openai",
) -> None:
    PROVIDER_REQUESTS.labels(provider, operation, outcome).inc()
    PROVIDER_DURATION.labels(provider, operation).observe(perf_counter() - started_at)


def _redact_mapping(value: Mapping[object, object]) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for nested_key, nested_value in value.items():
        key = str(nested_key)
        redacted[key] = (
            REDACTED
            if any(part in key.lower() for part in _SENSITIVE_KEY_PARTS)
            else _redact_value(nested_value)
        )
    return redacted


def _redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _redact_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    return value
