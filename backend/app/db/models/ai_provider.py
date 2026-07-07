"""User-scoped custom AI providers.

Each row represents one user-configured AI provider with:
  - name (display label, e.g. "OpenAI", "Groq", "My local Ollama")
  - base_url (OpenAI-compatible endpoint root, e.g. https://api.openai.com)
  - api_key (Fernet-encrypted at rest; optional for local providers)
  - models (JSON array of model IDs the user wants to expose, e.g. ["gpt-4o", "gpt-4o-mini"])
  - model_type ("chat" -> POST /v1/chat/completions (universal, default);
                "responses" -> POST /v1/responses (OpenAI-direct only))
  - tools_enabled (when False, the agent registers NO tools on this provider
                so the request body has no ``tools`` array — works around
                403s from certain g4f / free models)
  - is_active (soft toggle)

The frontend Config settings page CRUDs these via /api/v1/ai-providers.
The chat model picker reads from /api/v1/ai-providers to populate the
dropdown — no more hardcoded model list.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class AIProvider(Base, TimestampMixin):
    """A user-configured OpenAI-compatible AI provider."""

    __tablename__ = "ai_providers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    # Fernet-encrypted at rest using settings.SECRET_KEY; blank for local
    # providers that don't require auth.
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON array of strings: ["gpt-4o", "gpt-4o-mini", ...]
    models: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Which OpenAI API surface to call. Defaults to "chat" (universal).
    # See the module docstring above for the rationale.
    model_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="chat", server_default="chat"
    )
    # When False, the agent registers NO tools (no ``tools`` array in the
    # request body). Some providers (g4f / free models) 403 on any tool
    # payload — this lets the user still chat in text-only mode.
    tools_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    user: Mapped[User] = relationship("User", lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<AIProvider(name={self.name!r} base_url={self.base_url!r} "
            f"model_type={self.model_type!r} tools={self.tools_enabled} "
            f"active={self.is_active})>"
        )
