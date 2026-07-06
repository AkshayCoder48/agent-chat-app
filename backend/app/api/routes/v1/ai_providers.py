"""User-scoped AI provider settings.

CRUD endpoints at /api/v1/ai-providers for managing OpenAI-compatible
custom AI providers (base_url + optional api_key + list of model IDs).

A separate /test endpoint sends a minimal chat completions request to
verify the provider is reachable.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import AIProviderSvc, CurrentUser
from app.schemas.ai_provider import (
    AIProviderCreate,
    AIProviderList,
    AIProviderRead,
    AIProviderTestResult,
    AIProviderUpdate,
)

router = APIRouter()


def _to_read(p) -> AIProviderRead:
    return AIProviderRead(
        id=p.id,
        user_id=p.user_id,
        name=p.name,
        base_url=p.base_url,
        models=list(p.models or []),
        is_active=p.is_active,
        has_api_key=bool(p.api_key_encrypted),
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@router.get("", response_model=AIProviderList)
async def list_providers(
    service: AIProviderSvc, user: CurrentUser, active_only: bool = False
) -> Any:
    """List the current user's AI providers."""
    items, total = await service.list_for_user(user_id=user.id, active_only=active_only)
    return AIProviderList(items=[_to_read(p) for p in items], total=total)


@router.post(
    "",
    response_model=AIProviderRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_provider(
    data: AIProviderCreate, service: AIProviderSvc, user: CurrentUser
) -> Any:
    """Add a new custom AI provider."""
    p = await service.create(user_id=user.id, data=data)
    return _to_read(p)


@router.patch("/{provider_id}", response_model=AIProviderRead)
async def update_provider(
    provider_id: UUID,
    data: AIProviderUpdate,
    service: AIProviderSvc,
    user: CurrentUser,
) -> Any:
    """Patch an existing provider. Send api_key="" to clear it."""
    p = await service.update(user_id=user.id, provider_id=provider_id, data=data)
    return _to_read(p)


@router.delete(
    "/{provider_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_provider(
    provider_id: UUID, service: AIProviderSvc, user: CurrentUser
) -> None:
    """Delete a provider."""
    await service.delete(user_id=user.id, provider_id=provider_id)


@router.post("/{provider_id}/test", response_model=AIProviderTestResult)
async def test_provider(
    provider_id: UUID,
    service: AIProviderSvc,
    user: CurrentUser,
    model: str | None = None,
) -> Any:
    """Send a minimal chat completions request to verify the provider."""
    return await service.test(
        user_id=user.id, provider_id=provider_id, model=model
    )
