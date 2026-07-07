"""User settings, MCP server, and custom tool database models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class UserSettings(Base, TimestampMixin):
    """Per-user settings row (1:1 with :class:`User`).

    Stores the user's custom system prompt, encrypted third-party API keys
    (Hopx, Tavily, embeddings), and a free-form ``extra`` JSONB blob for
    future additions without a migration.
    """

    __tablename__ = "user_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    hopx_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    tavily_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    embeddings_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class MCPServer(Base, TimestampMixin):
    """A user-configured MCP server.

    The agent spins up the matching pydantic-ai toolset (stdio / SSE /
    streamable-http) at chat time so the server's tools become available.
    """

    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    transport: Mapped[str] = mapped_column(String(32), nullable=False)
    command: Mapped[str | None] = mapped_column(String(512), nullable=True)
    args: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    env: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    headers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )


class CustomTool(Base, TimestampMixin):
    """A user-defined tool (HTTP webhook or Python snippet).

    Loaded into the agent's toolset at chat time so the LLM can call it.
    """

    __tablename__ = "custom_tools"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    parameters_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    impl_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="http_webhook"
    )
    http_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    http_headers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    python_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
