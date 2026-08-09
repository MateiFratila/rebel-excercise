from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from rebel_dot.domain import FAQItem
from rebel_dot.domain.content import compute_content_hash, normalize_question
from rebel_dot.ops.faq_fixture import SourceFAQ, load_faq_fixture
from rebel_dot.ports import UnitOfWork


def build_faq_items(
    collection_id: UUID,
    source_items: Iterable[SourceFAQ],
    now: datetime,
) -> tuple[FAQItem, ...]:
    return tuple(
        FAQItem(
            id=uuid4(),
            collection_id=collection_id,
            question_raw=source.question,
            question_normalized=normalize_question(source.question),
            answer_raw=source.answer,
            category=source.category,
            content_hash=compute_content_hash(
                source.question,
                source.answer,
                source.category,
            ),
            source_metadata={},
            embedding=None,
            embedding_model=None,
            is_active=True,
            created_at=now,
            updated_at=now,
            embedded_at=None,
        )
        for source in source_items
    )


async def import_faq_fixture(
    unit_of_work: UnitOfWork,
    collection_id: UUID,
    fixture_path: Path,
    now: datetime,
) -> int:
    fixture = load_faq_fixture(fixture_path)
    items = build_faq_items(collection_id, fixture.knowledge_base_items, now)
    async with unit_of_work as transaction:
        return await transaction.faqs.upsert_many(items)
