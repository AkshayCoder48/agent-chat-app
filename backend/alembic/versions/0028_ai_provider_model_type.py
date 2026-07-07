
"""add model_type column to ai_providers

Revision ID: 0028_ai_provider_model_type
Revises: 0027_user_settings_env_vars

Adds a per-provider ``model_type`` column that controls which OpenAI API
surface the agent calls:
  * "chat"      -> POST /v1/chat/completions  (universal — default)
  * "responses" -> POST /v1/responses         (OpenAI-direct only)

Existing rows default to "chat" because most third-party OpenAI-compatible
providers (g4f.space, OpenRouter, Groq, Together, Ollama, vLLM, LM Studio, …)
only implement /v1/chat/completions. Routing them through OpenAIResponsesModel
is the root cause of the stuck-at-thinking bug — the SSE stream never starts
because /v1/responses returns 404 from those providers and pydantic-ai's
parser hangs forever waiting for the first chunk.
"""

revision = "0028_ai_provider_model_type"
down_revision = "0027_user_settings_env_vars"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op
    import sqlalchemy as sa

    op.add_column(
        "ai_providers",
        sa.Column(
            "model_type",
            sa.String(16),
            nullable=False,
            server_default="chat",
        ),
    )


def downgrade() -> None:
    from alembic import op

    op.drop_column("ai_providers", "model_type")
