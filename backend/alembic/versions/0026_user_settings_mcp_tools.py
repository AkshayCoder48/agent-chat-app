
"""create user_settings, mcp_servers, custom_tools tables

Revision ID: 0026_user_settings_mcp_tools
Revises: 0025_create_ai_providers
"""

revision = "0026_user_settings_mcp_tools"
down_revision = "0025_create_ai_providers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import UUID, JSONB

    # --- user_settings: one row per user, stores per-user overrides like the
    # custom system prompt, hopx sandbox API key (encrypted), tavily key, etc.
    op.create_table(
        "user_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("system_prompt_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("hopx_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("tavily_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("embeddings_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("extra", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # --- mcp_servers: per-user MCP server configurations. The agent loads
    # these at chat time and spins up MCPServerStdio/SSE/StreamableHTTP
    # toolsets so the configured tools become available to the LLM.
    op.create_table(
        "mcp_servers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("transport", sa.String(32), nullable=False),  # stdio | sse | streamable_http
        sa.Column("command", sa.String(512), nullable=True),  # for stdio
        sa.Column("args", JSONB, nullable=False, server_default="[]"),  # for stdio
        sa.Column("env", JSONB, nullable=False, server_default="{}"),  # for stdio
        sa.Column("url", sa.String(512), nullable=True),  # for sse / streamable_http
        sa.Column("headers", JSONB, nullable=False, server_default="{}"),  # for sse / streamable_http
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true"), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # --- custom_tools: per-user custom tool definitions (name + JSON schema
    # + Python source or HTTP endpoint). Loaded into the agent's toolset at
    # chat time.
    op.create_table(
        "custom_tools",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("parameters_schema", JSONB, nullable=False, server_default="{}"),
        # Implementation kind: 'http_webhook' | 'python_snippet'
        sa.Column("impl_kind", sa.String(32), nullable=False, server_default="http_webhook"),
        # For http_webhook: the URL to POST to.
        sa.Column("http_url", sa.String(512), nullable=True),
        sa.Column("http_headers", JSONB, nullable=False, server_default="{}"),
        # For python_snippet: the source code (executed in a sandbox).
        sa.Column("python_source", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true"), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint("uq_custom_tools_user_name", "custom_tools", ["user_id", "name"])


def downgrade() -> None:
    from alembic import op
    op.drop_constraint("uq_custom_tools_user_name", "custom_tools", type_="unique")
    op.drop_table("custom_tools")
    op.drop_table("mcp_servers")
    op.drop_table("user_settings")
