"""Create core FAQ, embedding job, and session tables."""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260809_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "faq_collections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "embedding_dimensions BETWEEN 1 AND 3072",
            name=op.f("ck_faq_collections_valid_embedding_dimensions"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'embedding', 'ready', 'active', 'archived')",
            name=op.f("ck_faq_collections_valid_status"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_faq_collections_positive_version")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faq_collections")),
        sa.UniqueConstraint("name", "version", name="collection_name_version"),
    )
    op.create_index(
        "uq_faq_collections_single_active",
        "faq_collections",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_auth_sessions_expiry_after_creation")
        ),
        sa.CheckConstraint(
            "length(token_digest) = 64", name=op.f("ck_auth_sessions_valid_token_digest")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_auth_sessions_token_digest")),
    )
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"], unique=False)

    op.create_table(
        "embedding_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "processed_count + failed_count <= requested_count",
            name=op.f("ck_embedding_jobs_counts_within_requested"),
        ),
        sa.CheckConstraint(
            "requested_count >= 0 AND processed_count >= 0 AND failed_count >= 0",
            name=op.f("ck_embedding_jobs_nonnegative_counts"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partially_failed', 'failed')",
            name=op.f("ck_embedding_jobs_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["faq_collections.id"],
            name=op.f("fk_embedding_jobs_collection_id_faq_collections"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embedding_jobs")),
    )
    op.create_index(
        "ix_embedding_jobs_status_created",
        "embedding_jobs",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "faq_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_raw", sa.Text(), nullable=False),
        sa.Column("question_normalized", sa.Text(), nullable=False),
        sa.Column("answer_raw", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
        sa.Column("embedded_content_hash", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "embedded_content_hash IS NULL OR length(embedded_content_hash) = 64",
            name=op.f("ck_faq_items_valid_embedded_content_hash"),
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64", name=op.f("ck_faq_items_valid_content_hash")
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["faq_collections.id"],
            name=op.f("fk_faq_items_collection_id_faq_collections"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faq_items")),
        sa.UniqueConstraint("collection_id", "content_hash", name="collection_content_hash"),
    )
    op.create_index(
        "ix_faq_items_collection_active",
        "faq_items",
        ["collection_id", "is_active"],
        unique=False,
    )

    op.execute(
        """
        CREATE FUNCTION validate_faq_embedding() RETURNS trigger AS $$
        DECLARE
            expected_dimensions integer;
            expected_model text;
        BEGIN
            IF NEW.embedding IS NOT NULL THEN
                SELECT embedding_dimensions, embedding_model
                INTO expected_dimensions, expected_model
                FROM faq_collections
                WHERE id = NEW.collection_id;

                IF vector_dims(NEW.embedding) <> expected_dimensions THEN
                    RAISE EXCEPTION 'embedding dimensions do not match collection'
                        USING ERRCODE = 'check_violation';
                END IF;
                IF NEW.embedding_model IS DISTINCT FROM expected_model THEN
                    RAISE EXCEPTION 'embedding model does not match collection'
                        USING ERRCODE = 'check_violation';
                END IF;
                IF NEW.embedded_content_hash IS DISTINCT FROM NEW.content_hash THEN
                    RAISE EXCEPTION 'embedding content hash is stale'
                        USING ERRCODE = 'check_violation';
                END IF;
                IF NEW.embedded_at IS NULL THEN
                    RAISE EXCEPTION 'embedded_at is required with an embedding'
                        USING ERRCODE = 'check_violation';
                END IF;
            ELSIF NEW.embedding_model IS NOT NULL
                OR NEW.embedded_content_hash IS NOT NULL
                OR NEW.embedded_at IS NOT NULL THEN
                RAISE EXCEPTION 'embedding metadata requires an embedding'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_validate_faq_embedding
        BEFORE INSERT OR UPDATE ON faq_items
        FOR EACH ROW EXECUTE FUNCTION validate_faq_embedding()
        """
    )
    op.execute(
        """
        CREATE INDEX ix_faq_items_embedding_hnsw_1536
        ON faq_items USING hnsw ((embedding::vector(1536)) vector_cosine_ops)
        WHERE embedding IS NOT NULL
          AND is_active
          AND embedding_model = 'text-embedding-3-small'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_faq_items_embedding_hnsw_1536")
    op.execute("DROP TRIGGER IF EXISTS trg_validate_faq_embedding ON faq_items")
    op.execute("DROP FUNCTION IF EXISTS validate_faq_embedding")
    op.drop_index("ix_faq_items_collection_active", table_name="faq_items")
    op.drop_table("faq_items")
    op.drop_index("ix_embedding_jobs_status_created", table_name="embedding_jobs")
    op.drop_table("embedding_jobs")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("uq_faq_collections_single_active", table_name="faq_collections")
    op.drop_table("faq_collections")
    op.execute("DROP EXTENSION IF EXISTS vector")
