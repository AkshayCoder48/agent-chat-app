
"""add tools_enabled column to ai_providers

Revision ID: 0029_ai_provider_tools_enabled
Revises: 0028_ai_provider_model_type

Adds a per-provider ``tools_enabled`` boolean column. When False, the agent
registers NO tools on this provider so the request body has no ``tools``
array. This works around HTTP 403 errors returned by some providers
(notably certain g4f / free models) when any tool payload is sent.

Existing rows default to True so legacy providers keep their existing
behavior unless the user explicitly disables tools in the settings UI.
"""

revision = "0029_ai_provider_tools_enabled"
down_revision = "0028_ai_provider_model_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op
    import sqlalchemy as sa

    op.add_column(
        "ai_providers",
        sa.Column(
            "tools_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    from alembic import op

    op.drop_column("ai_providers", "tools_enabled")
