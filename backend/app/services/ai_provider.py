"""Business logic for user-scoped AI providers (PostgreSQL async).

A provider is an OpenAI-compatible endpoint (base_url + optional api_key)
plus a list of model IDs the user wants to expose in the chat picker.
"""

from __future__ import annotations

import json
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.ai_provider import AIProvider
from app.repositories import ai_provider_repo
from app.schemas.ai_provider import AIProviderCreate, AIProviderTestResult, AIProviderUpdate


class AIProviderService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_user(
        self, *, user_id: UUID, active_only: bool = False
    ) -> tuple[list[AIProvider], int]:
        return await ai_provider_repo.list_for_user(
            self.db, user_id=user_id, active_only=active_only
        )

    async def get_owned_or_404(self, *, user_id: UUID, provider_id: UUID) -> AIProvider:
        provider = await ai_provider_repo.get_by_id(self.db, provider_id)
        if provider is None or provider.user_id != user_id:
            raise NotFoundError(
                message="AI provider not found", details={"provider_id": str(provider_id)}
            )
        return provider

    async def create(self, *, user_id: UUID, data: AIProviderCreate) -> AIProvider:
        # Normalize base_url — strip trailing slash so we can append /v1/chat/completions cleanly.
        base_url = (data.base_url or "").rstrip("/")
        if not base_url:
            raise BadRequestError(message="base_url is required")
        return await ai_provider_repo.create(
            self.db,
            user_id=user_id,
            name=data.name,
            base_url=base_url,
            api_key=data.api_key,
            models=list(data.models),
            is_active=data.is_active,
            model_type=data.model_type,
            tools_enabled=data.tools_enabled,
        )

    async def update(
        self, *, user_id: UUID, provider_id: UUID, data: AIProviderUpdate
    ) -> AIProvider:
        provider = await self.get_owned_or_404(user_id=user_id, provider_id=provider_id)
        update_data = data.model_dump(exclude_unset=True)
        if "base_url" in update_data and update_data["base_url"]:
            update_data["base_url"] = update_data["base_url"].rstrip("/")
        return await ai_provider_repo.update(
            self.db, db_provider=provider, update_data=update_data
        )

    async def delete(self, *, user_id: UUID, provider_id: UUID) -> None:
        provider = await self.get_owned_or_404(user_id=user_id, provider_id=provider_id)
        await ai_provider_repo.delete(self.db, db_provider=provider)

    async def test(
        self, *, user_id: UUID, provider_id: UUID, model: str | None = None
    ) -> AIProviderTestResult:
        """Send a minimal /v1/chat/completions request to verify the provider.

        Uses httpx with a 15s timeout. Returns a structured result so the
        frontend can show the status code + body snippet.
        """
        provider = await self.get_owned_or_404(user_id=user_id, provider_id=provider_id)
        if not model:
            if not provider.models:
                return AIProviderTestResult(
                    ok=False,
                    detail="No model configured for this provider. Add at least one model ID first.",
                )
            model = provider.models[0]

        api_key = ai_provider_repo.get_decrypted_api_key(provider)
        # Compose the OpenAI-compatible chat completions URL.
        base = provider.base_url.rstrip("/")
        # If the user already ended with /v1 or /v1/, just append /chat/completions.
        if base.endswith("/v1"):
            url = base + "/chat/completions"
        elif "/v1/" in base and base.endswith("/chat/completions"):
            url = base  # already a full endpoint URL
        elif "/chat/completions" in base:
            url = base
        else:
            url = base + "/v1/chat/completions"

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
            "max_tokens": 16,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
        except httpx.RequestError as exc:
            return AIProviderTestResult(ok=False, detail=f"Request failed: {exc!s}")
        except Exception as exc:  # noqa: BLE001
            return AIProviderTestResult(ok=False, detail=f"Unexpected error: {exc!s}")

        if resp.status_code >= 400:
            # Try to extract the response body for debugging.
            try:
                body_text = resp.text[:500]
            except Exception:  # noqa: BLE001
                body_text = None
            return AIProviderTestResult(
                ok=False,
                status_code=resp.status_code,
                detail=f"HTTP {resp.status_code}: {body_text}",
            )

        # Try to extract the assistant message text.
        sample: str | None = None
        try:
            body = resp.json()
            sample = body.get("choices", [{}])[0].get("message", {}).get("content")
        except json.JSONDecodeError:
            sample = None
        except Exception:  # noqa: BLE001
            sample = None

        return AIProviderTestResult(
            ok=True,
            status_code=resp.status_code,
            sample_response=sample,
        )
