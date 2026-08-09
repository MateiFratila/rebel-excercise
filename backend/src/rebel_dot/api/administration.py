from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from sqlalchemy.exc import IntegrityError

from rebel_dot.api.authentication import get_session, require_allowed_origin
from rebel_dot.api.errors import APIError
from rebel_dot.api.schemas import (
    BulkUpsertFAQItemsRequest,
    BulkUpsertFAQItemsResponse,
    CollectionReadinessResponse,
    CollectionResponse,
    CreateCollectionRequest,
    EmbeddingJobResponse,
    FAQItemInput,
    FAQItemResponse,
    UpdateFAQItemRequest,
)
from rebel_dot.application.embeddings import EmbeddingJobService
from rebel_dot.application.knowledge import (
    CollectionNotReadyError,
    CollectionReadiness,
    FAQItemDraft,
    IncompatibleCollectionError,
    KnowledgeService,
)
from rebel_dot.domain import (
    EmbeddingJob,
    ErrorCode,
    FAQCollection,
    FAQItem,
    OptimisticConcurrencyError,
)
from rebel_dot.ports import TaskDispatcher

router = APIRouter(
    prefix="/admin",
    tags=["administration"],
    dependencies=[Depends(get_session)],
)


def get_knowledge_service(request: Request) -> KnowledgeService:
    return cast(KnowledgeService, request.app.state.knowledge_service)


def get_embedding_job_service(request: Request) -> EmbeddingJobService:
    return cast(EmbeddingJobService, request.app.state.embedding_job_service)


def get_task_dispatcher(request: Request) -> TaskDispatcher:
    return cast(TaskDispatcher, request.app.state.task_dispatcher)


@router.get("/collections", response_model=list[CollectionResponse])
async def list_collections(
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> list[CollectionResponse]:
    return [
        _collection_response(collection, readiness)
        for collection, readiness in await service.list_collections()
    ]


@router.post(
    "/collections",
    response_model=CollectionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_allowed_origin)],
)
async def create_collection(
    payload: CreateCollectionRequest,
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> CollectionResponse:
    try:
        collection = await service.create_collection(
            payload.name,
            payload.embedding_model,
            payload.embedding_dimensions,
        )
    except IncompatibleCollectionError as error:
        raise _conflict("Collection embedding configuration is incompatible") from error
    except IntegrityError as error:
        raise _conflict("Collection version already exists") from error
    return _collection_response(
        collection,
        CollectionReadiness(active_items=0, pending_items=0),
    )


@router.get(
    "/collections/{collection_id}/readiness",
    response_model=CollectionReadinessResponse,
)
async def collection_readiness(
    collection_id: UUID,
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> CollectionReadinessResponse:
    try:
        return _readiness_response(await service.readiness(collection_id))
    except LookupError as error:
        raise _not_found("Collection not found") from error
    except IncompatibleCollectionError as error:
        raise _conflict("Collection embedding configuration is incompatible") from error


@router.get(
    "/collections/{collection_id}/items",
    response_model=list[FAQItemResponse],
)
async def list_items(
    collection_id: UUID,
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> list[FAQItemResponse]:
    try:
        return [_item_response(item) for item in await service.list_items(collection_id)]
    except LookupError as error:
        raise _not_found("Collection not found") from error


@router.post(
    "/collections/{collection_id}/items",
    response_model=BulkUpsertFAQItemsResponse,
    dependencies=[Depends(require_allowed_origin)],
)
async def upsert_items(
    collection_id: UUID,
    payload: BulkUpsertFAQItemsRequest,
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> BulkUpsertFAQItemsResponse:
    try:
        changed_count = await service.upsert_items(
            collection_id,
            tuple(_draft(item) for item in payload.items),
        )
    except LookupError as error:
        raise _not_found("Collection not found") from error
    return BulkUpsertFAQItemsResponse(changed_count=changed_count)


@router.patch(
    "/collections/{collection_id}/items/{item_id}",
    response_model=FAQItemResponse,
    dependencies=[Depends(require_allowed_origin)],
)
async def update_item(
    collection_id: UUID,
    item_id: UUID,
    payload: UpdateFAQItemRequest,
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> FAQItemResponse:
    try:
        item = await service.update_item(
            collection_id,
            item_id,
            payload.expected_updated_at,
            _draft(payload),
        )
    except LookupError as error:
        raise _not_found("FAQ item not found") from error
    except OptimisticConcurrencyError as error:
        raise _conflict("FAQ item was modified by another request") from error
    return _item_response(item)


@router.delete(
    "/collections/{collection_id}/items/{item_id}",
    response_model=FAQItemResponse,
    dependencies=[Depends(require_allowed_origin)],
)
async def deactivate_item(
    collection_id: UUID,
    item_id: UUID,
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> FAQItemResponse:
    try:
        return _item_response(await service.deactivate_item(collection_id, item_id))
    except LookupError as error:
        raise _not_found("FAQ item not found") from error


@router.post(
    "/collections/{collection_id}/embedding-jobs",
    response_model=EmbeddingJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_allowed_origin)],
)
async def queue_embedding_job(
    collection_id: UUID,
    response: Response,
    background_tasks: BackgroundTasks,
    service: Annotated[EmbeddingJobService, Depends(get_embedding_job_service)],
    dispatcher: Annotated[TaskDispatcher, Depends(get_task_dispatcher)],
) -> EmbeddingJobResponse:
    try:
        job = await service.queue(collection_id)
    except LookupError as error:
        raise _not_found("Collection not found") from error
    location = f"/admin/jobs/{job.id}"
    response.headers["Location"] = location
    if job.status.value == "queued":
        background_tasks.add_task(dispatcher.dispatch_embedding_job, job.id)
    return _job_response(job)


@router.get("/jobs/{job_id}", response_model=EmbeddingJobResponse)
async def get_embedding_job(
    job_id: UUID,
    service: Annotated[EmbeddingJobService, Depends(get_embedding_job_service)],
) -> EmbeddingJobResponse:
    job = await service.get(job_id)
    if job is None:
        raise _not_found("Embedding job not found")
    return _job_response(job)


@router.post(
    "/collections/{collection_id}/activate",
    response_model=CollectionResponse,
    dependencies=[Depends(require_allowed_origin)],
)
async def activate_collection(
    collection_id: UUID,
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> CollectionResponse:
    try:
        collection = await service.activate(collection_id)
        readiness = await service.readiness(collection_id)
    except LookupError as error:
        raise _not_found("Collection not found") from error
    except (CollectionNotReadyError, IncompatibleCollectionError) as error:
        raise _conflict("Collection is not ready for activation") from error
    return _collection_response(collection, readiness)


def _draft(item: FAQItemInput) -> FAQItemDraft:
    return FAQItemDraft(
        question=item.question,
        answer=item.answer,
        category=item.category,
        source_metadata=item.source_metadata,
    )


def _collection_response(
    collection: FAQCollection,
    readiness: CollectionReadiness,
) -> CollectionResponse:
    return CollectionResponse(
        id=collection.id,
        name=collection.name,
        version=collection.version,
        status=collection.status,
        embedding_model=collection.embedding_model,
        embedding_dimensions=collection.embedding_dimensions,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
        readiness=_readiness_response(readiness),
    )


def _readiness_response(readiness: CollectionReadiness) -> CollectionReadinessResponse:
    return CollectionReadinessResponse(
        ready=readiness.ready,
        active_items=readiness.active_items,
        pending_items=readiness.pending_items,
    )


def _item_response(item: FAQItem) -> FAQItemResponse:
    return FAQItemResponse(
        id=item.id,
        collection_id=item.collection_id,
        question=item.question_raw,
        answer=item.answer_raw,
        category=item.category,
        source_metadata=dict(item.source_metadata),
        is_active=item.is_active,
        embedding_model=item.embedding_model,
        embedded_at=item.embedded_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _job_response(job: EmbeddingJob) -> EmbeddingJobResponse:
    return EmbeddingJobResponse(
        job_id=job.id,
        status=job.status,
        requested_count=job.requested_count,
        processed_count=job.processed_count,
        failed_count=job.failed_count,
        error_summary=job.error_summary,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _not_found(message: str) -> APIError:
    return APIError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, message)


def _conflict(message: str) -> APIError:
    return APIError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, message)
