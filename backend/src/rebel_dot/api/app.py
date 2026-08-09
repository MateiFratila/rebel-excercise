from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from rebel_dot.adapters.db.database import create_database_engine, create_session_factory
from rebel_dot.adapters.db.unit_of_work import SQLAlchemyUnitOfWork
from rebel_dot.adapters.openai_chat import OpenAIChatProvider, OpenAIScopeClassifier
from rebel_dot.adapters.openai_embeddings import OpenAIEmbeddingProvider
from rebel_dot.adapters.task_dispatcher import DatabaseTaskDispatcher
from rebel_dot.api.administration import router as administration_router
from rebel_dot.api.authentication import router as authentication_router
from rebel_dot.api.errors import install_error_handlers
from rebel_dot.api.questions import router as questions_router
from rebel_dot.application.authentication import LoginRateLimiter, SessionService
from rebel_dot.application.embeddings import (
    DatabaseEmbeddingRunner,
    EmbeddingJobService,
    RetrievalService,
)
from rebel_dot.application.knowledge import KnowledgeService
from rebel_dot.application.routing import (
    ConfidenceRoutingPolicy,
    RuleBasedOutputGuardrail,
    RuleBasedQuestionGuardrail,
)
from rebel_dot.application.workflow import QuestionAnsweringService
from rebel_dot.core import Environment, Settings
from rebel_dot.ports import (
    ChatProvider,
    EmbeddingProvider,
    QuestionAnswerer,
    ScopeClassifier,
    TaskDispatcher,
    UnitOfWork,
)


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: Literal["ok", "not_ready"]


API_PATH_PREFIXES = frozenset(
    {"admin", "ask-question", "auth", "docs", "health", "openapi.json", "redoc"}
)


def create_app(
    settings: Settings | None = None,
    session_service: SessionService | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    task_dispatcher: TaskDispatcher | None = None,
    question_answerer: QuestionAnswerer | None = None,
    scope_classifier: ScopeClassifier | None = None,
    chat_provider: ChatProvider | None = None,
    static_directory: str | Path | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()  # type: ignore[call-arg]
    database_engine: AsyncEngine = create_database_engine(str(resolved_settings.database_url))
    session_factory = create_session_factory(database_engine)

    def create_unit_of_work() -> UnitOfWork:
        return SQLAlchemyUnitOfWork(session_factory)

    if session_service is None:
        session_service = SessionService(
            password_hash=resolved_settings.shared_password_hash.get_secret_value(),
            session_lifetime_seconds=resolved_settings.session_lifetime_seconds,
            unit_of_work_factory=create_unit_of_work,
            rate_limiter=LoginRateLimiter(
                limit=resolved_settings.login_rate_limit,
                window_seconds=resolved_settings.login_rate_window_seconds,
            ),
        )

    if embedding_provider is None:
        embedding_provider = OpenAIEmbeddingProvider(
            model=resolved_settings.embedding_model,
            dimensions=resolved_settings.embedding_dimensions,
            api_key=resolved_settings.openai_api_key,
            timeout_seconds=resolved_settings.openai_timeout_seconds,
            max_retries=resolved_settings.openai_max_retries,
            batch_size=resolved_settings.embedding_batch_size,
        )

    knowledge_service = KnowledgeService(
        unit_of_work_factory=create_unit_of_work,
        embedding_model=resolved_settings.embedding_model,
        embedding_dimensions=resolved_settings.embedding_dimensions,
    )
    embedding_job_service = EmbeddingJobService(
        unit_of_work_factory=create_unit_of_work,
    )
    retrieval_service = RetrievalService(
        unit_of_work_factory=create_unit_of_work,
        provider=embedding_provider,
        embedding_model=resolved_settings.embedding_model,
        embedding_dimensions=resolved_settings.embedding_dimensions,
    )
    if question_answerer is None:
        if scope_classifier is None:
            scope_classifier = OpenAIScopeClassifier(
                model=resolved_settings.chat_model,
                api_key=resolved_settings.openai_api_key,
                timeout_seconds=resolved_settings.openai_timeout_seconds,
                max_retries=resolved_settings.openai_max_retries,
            )
        if chat_provider is None:
            chat_provider = OpenAIChatProvider(
                model=resolved_settings.chat_model,
                api_key=resolved_settings.openai_api_key,
                timeout_seconds=resolved_settings.openai_timeout_seconds,
                max_retries=resolved_settings.openai_max_retries,
            )
        question_answerer = QuestionAnsweringService(
            question_guardrail=RuleBasedQuestionGuardrail(resolved_settings.max_question_chars),
            output_guardrail=RuleBasedOutputGuardrail(),
            scope_classifier=scope_classifier,
            retriever=retrieval_service,
            routing_policy=ConfidenceRoutingPolicy(
                resolved_settings.local_similarity_threshold,
                resolved_settings.local_similarity_margin,
                resolved_settings.scope_confidence_threshold,
            ),
            chat_provider=chat_provider,
            scope_confidence_threshold=resolved_settings.scope_confidence_threshold,
        )
    managed_dispatcher: DatabaseTaskDispatcher | None = None
    if task_dispatcher is None:
        runner = DatabaseEmbeddingRunner(
            unit_of_work_factory=create_unit_of_work,
            provider=embedding_provider,
            batch_size=resolved_settings.embedding_batch_size,
            stale_after_seconds=resolved_settings.job_stale_after_seconds,
        )
        managed_dispatcher = DatabaseTaskDispatcher(
            runner,
            poll_interval_seconds=resolved_settings.job_poll_interval_seconds,
        )
        task_dispatcher = managed_dispatcher

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if managed_dispatcher is not None:
            await managed_dispatcher.start()
        try:
            yield
        finally:
            if managed_dispatcher is not None:
                await managed_dispatcher.close()
            await database_engine.dispose()

    app = FastAPI(
        title="Semantic FAQ Assistant",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.session_service = session_service
    app.state.knowledge_service = knowledge_service
    app.state.embedding_job_service = embedding_job_service
    app.state.retrieval_service = retrieval_service
    app.state.question_answerer = question_answerer
    app.state.task_dispatcher = task_dispatcher
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "PATCH", "PUT"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )
    install_error_handlers(app)
    app.include_router(authentication_router)
    app.include_router(administration_router)
    app.include_router(questions_router)

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def health_live() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get(
        "/health/ready",
        response_model=ReadinessResponse,
        tags=["health"],
        responses={503: {"model": ReadinessResponse}},
    )
    async def health_ready(response: Response) -> ReadinessResponse:
        try:
            ready = await knowledge_service.application_ready()
        except Exception:
            ready = False
        if not ready:
            response.status_code = 503
            return ReadinessResponse(status="not_ready")
        return ReadinessResponse(status="ok")

    bundled_static_directory = Path("static")
    resolved_static_directory = (
        Path(static_directory)
        if static_directory is not None
        else bundled_static_directory
        if resolved_settings.environment is Environment.PRODUCTION
        or bundled_static_directory.is_dir()
        else None
    )
    if resolved_static_directory is not None:
        index_path = resolved_static_directory / "index.html"
        app.mount(
            "/assets",
            StaticFiles(directory=resolved_static_directory / "assets"),
            name="spa-assets",
        )

        @app.api_route(
            "/", methods=["GET", "HEAD"], include_in_schema=False, response_class=FileResponse
        )
        async def spa_index() -> FileResponse:
            return FileResponse(index_path)

        @app.api_route(
            "/{full_path:path}",
            methods=["GET", "HEAD"],
            include_in_schema=False,
            response_class=FileResponse,
        )
        async def spa_fallback(full_path: str) -> FileResponse:
            if full_path.partition("/")[0] in API_PATH_PREFIXES:
                raise HTTPException(status_code=404)
            static_root = resolved_static_directory.resolve()
            requested_file = (static_root / full_path).resolve()
            if requested_file.is_relative_to(static_root) and requested_file.is_file():
                return FileResponse(requested_file)
            return FileResponse(index_path)

    return app
