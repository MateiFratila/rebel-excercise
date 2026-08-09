"""Scope the default HNSW index to matching vector dimensions.

Revision ID: 20260809_0002
Revises: 20260809_0001
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260809_0002"
down_revision: str | None = "20260809_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_faq_items_embedding_hnsw_1536")
    op.execute(
        """
        CREATE INDEX ix_faq_items_embedding_hnsw_1536
        ON faq_items USING hnsw ((embedding::vector(1536)) vector_cosine_ops)
        WHERE embedding IS NOT NULL
          AND is_active
          AND embedding_model = 'text-embedding-3-small'
          AND vector_dims(embedding) = 1536
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_faq_items_embedding_hnsw_1536")
    op.execute(
        """
        CREATE INDEX ix_faq_items_embedding_hnsw_1536
        ON faq_items USING hnsw ((embedding::vector(1536)) vector_cosine_ops)
        WHERE embedding IS NOT NULL
          AND is_active
          AND embedding_model = 'text-embedding-3-small'
        """
    )
