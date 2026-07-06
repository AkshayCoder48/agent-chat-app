"""Data access for user-scoped AI providers (PostgreSQL async)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt_value, encrypt_value
from app.db.models.ai_provider import AIProvider


def _encrypt_api_key(plaintext: str | None) -> str | None:
    if not plaintext:
        return None
    return encrypt_value(plaintext, settings.SECRET_KEY)


def _decrypt_api_key(stored: str | None) -> str:
    if not stored:
        return ""
    return decrypt_value(stored, settings.SECRET_KEY)


async def get_by_id(db: AsyncSession, provider_id: UUID) -> AIProvider | None:
    result = await db.execute(select(AIProvider).where(AIProvider.id == provider_id))
    return result.scalar_one_or_none()


async def list_for_user(
    db: AsyncSession, *, user_id: UUID, active_only: bool = False
) -> tuple[list[AIProvider], int]:
    stmt = (
        select(AIProvider)
        .where(AIProvider.user_id == user_id)
        .order_by(AIProvider.created_at.asc())
    )
    if active_only:
        stmt = stmt.where(AIProvider.is_active.is_(True))
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()
    items = list((await db.execute(stmt)).scalars())
    return items, total


async def create(
    db: AsyncSession,
    *,
    user_id: UUID,
    name: str,
    base_url: str,
    api_key: str | None,
    models: list[str],
    is_active: bool = True,
) -> AIProvider:
    provider = AIProvider(
        user_id=user_id,
        name=name,
        base_url=base_url,
        api_key_encrypted=_encrypt_api_key(api_key),
        models=models,
        is_active=is_active,
    )
    db.add(provider)
    await db.flush()
    await db.refresh(provider)
    return provider


async def update(
    db: AsyncSession,
    *,
    db_provider: AIProvider,
    update_data: dict[str, Any],
) -> AIProvider:
    # Handle api_key specially — encrypt before storing.
    if "api_key" in update_data:
        plain = update_data.pop("api_key")
        if plain is None or plain == "":
            # Empty string means "clear the key"
            db_provider.api_key_encrypted = None
        else:
            db_provider.api_key_encrypted = _encrypt_api_key(plain)

    for field, value in update_data.items():
        setattr(db_provider, field, value)
    await db.flush()
    await db.refresh(db_provider)
    return db_provider


async def delete(db: AsyncSession, *, db_provider: AIProvider) -> None:
    await db.delete(db_provider)
    await db.flush()


def get_decrypted_api_key(db_provider: AIProvider) -> str:
    """Return the plaintext API key for outbound calls to the provider."""
    return _decrypt_api_key(db_provider.api_key_encrypted)
