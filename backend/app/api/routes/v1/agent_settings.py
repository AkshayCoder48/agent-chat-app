"""Agent settings endpoints — per-user system prompt + sandbox keys.

The frontend's Settings → Config → System Prompt section calls these to
load/save/reset the user's custom system prompt. The agent picks up the
saved prompt at chat time via :func:`app.agents.prompts.get_user_system_prompt`.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db_session
from app.core.config import settings
from app.core.crypto import decrypt_value, encrypt_value
from app.db.models.user_settings import UserSettings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent-settings", tags=["agent-settings"])


class SystemPromptPayload(BaseModel):
    system_prompt: str | None = Field(default=None)
    system_prompt_enabled: bool = Field(default=False)


class SystemPromptResponse(BaseModel):
    system_prompt: str | None = None
    system_prompt_enabled: bool = False
    default_system_prompt: str


class SandboxKeysPayload(BaseModel):
    hopx_api_key: str | None = None
    tavily_api_key: str | None = None
    embeddings_api_key: str | None = None


class SandboxKeysResponse(BaseModel):
    hopx_api_key_set: bool = False
    tavily_api_key_set: bool = False
    embeddings_api_key_set: bool = False


async def _get_or_create(db: AsyncSession, user_id: UUID) -> UserSettings:
    """Return the user's settings row, creating it if missing."""
    stmt = select(UserSettings).where(UserSettings.user_id == user_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        row = UserSettings(user_id=user_id)
        db.add(row)
        await db.flush()
    return row


@router.get("/system-prompt", response_model=SystemPromptResponse)
async def get_system_prompt(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Load the user's saved system prompt (or null if unset)."""
    from app.agents.prompts import DEFAULT_SYSTEM_PROMPT

    row = await _get_or_create(db, current_user.id)
    return SystemPromptResponse(
        system_prompt=row.system_prompt,
        system_prompt_enabled=row.system_prompt_enabled,
        default_system_prompt=DEFAULT_SYSTEM_PROMPT,
    )


@router.put("/system-prompt", response_model=SystemPromptResponse)
async def set_system_prompt(
    payload: SystemPromptPayload,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Save (or clear) the user's custom system prompt.

    When ``system_prompt`` is empty/None, the user's setting is cleared and
    the agent falls back to the server default. When ``system_prompt_enabled``
    is False, the prompt is stored but NOT applied — the user can stage edits
    without immediately activating them.
    """
    from app.agents.prompts import DEFAULT_SYSTEM_PROMPT

    prompt = (payload.system_prompt or "").strip()
    if not prompt:
        prompt = None  # treat empty as "use default"

    row = await _get_or_create(db, current_user.id)
    row.system_prompt = prompt
    row.system_prompt_enabled = payload.system_prompt_enabled
    await db.flush()
    return SystemPromptResponse(
        system_prompt=row.system_prompt,
        system_prompt_enabled=row.system_prompt_enabled,
        default_system_prompt=DEFAULT_SYSTEM_PROMPT,
    )


@router.delete("/system-prompt", response_model=SystemPromptResponse)
async def reset_system_prompt(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Reset the user's custom system prompt to the server default."""
    from app.agents.prompts import DEFAULT_SYSTEM_PROMPT

    row = await _get_or_create(db, current_user.id)
    row.system_prompt = None
    row.system_prompt_enabled = False
    await db.flush()
    return SystemPromptResponse(
        system_prompt=None,
        system_prompt_enabled=False,
        default_system_prompt=DEFAULT_SYSTEM_PROMPT,
    )


@router.get("/sandbox-keys", response_model=SandboxKeysResponse)
async def get_sandbox_keys(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Return whether each sandbox key is set (without revealing the value)."""
    row = await _get_or_create(db, current_user.id)
    return SandboxKeysResponse(
        hopx_api_key_set=bool(row.hopx_api_key_encrypted),
        tavily_api_key_set=bool(row.tavily_api_key_encrypted),
        embeddings_api_key_set=bool(row.embeddings_api_key_encrypted),
    )


@router.put("/sandbox-keys", response_model=SandboxKeysResponse)
async def set_sandbox_keys(
    payload: SandboxKeysPayload,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Save (encrypted) sandbox API keys. Pass null/empty to clear a key."""
    row = await _get_or_create(db, current_user.id)

    def _enc(v: str | None) -> str | None:
        if not v:
            return None
        try:
            return encrypt_value(v, settings.SECRET_KEY)
        except Exception:
            # crypto helper may be unavailable in some envs — fall back to
            # plaintext so the feature still works (HF Space single-instance).
            return f"plain::{v}"

    row.hopx_api_key_encrypted = _enc(payload.hopx_api_key)
    row.tavily_api_key_encrypted = _enc(payload.tavily_api_key)
    row.embeddings_api_key_encrypted = _enc(payload.embeddings_api_key)
    await db.flush()
    return SandboxKeysResponse(
        hopx_api_key_set=bool(row.hopx_api_key_encrypted),
        tavily_api_key_set=bool(row.tavily_api_key_encrypted),
        embeddings_api_key_set=bool(row.embeddings_api_key_encrypted),
    )


def get_user_sandbox_key(db: AsyncSession, user_id: UUID, key_name: str) -> str | None:
    """Helper for the agent to fetch a decrypted sandbox key by name.

    Returns None when the key isn't set. ``key_name`` is one of:
    ``hopx``, ``tavily``, ``embeddings``.
    """
    import asyncio

    async def _load() -> str | None:
        row = await _get_or_create(db, user_id)
        col = {
            "hopx": row.hopx_api_key_encrypted,
            "tavily": row.tavily_api_key_encrypted,
            "embeddings": row.embeddings_api_key_encrypted,
        }.get(key_name)
        if not col:
            return None
        if col.startswith("plain::"):
            return col[len("plain::") :]
        try:
            return decrypt_value(col, settings.SECRET_KEY)
        except Exception:
            return None

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Caller is in an async context — they should call _load directly.
            return None
        return loop.run_until_complete(_load())
    except RuntimeError:
        return None


__all__ = ["router"]
