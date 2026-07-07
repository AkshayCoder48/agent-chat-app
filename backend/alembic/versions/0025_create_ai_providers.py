
"""create ai_providers table

Revision ID: 0025_create_ai_providers
Revises: 0024_create_webhook_tables
"""

revision = "0025_create_ai_providers"
down_revision = "0024_create_webhook_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import UUID, JSONB

    op.create_table(
        "ai_providers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("models", JSONB, nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true"), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_ai_providers_user_id", "ai_providers", ["user_id"])


def downgrade() -> None:
    from alembic import op
    op.drop_index("ix_ai_providers_user_id", table_name="ai_providers")
    op.drop_table("ai_providers")
