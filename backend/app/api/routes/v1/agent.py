
# Route is lifecycle plumbing only — auth, accept, dispatch loop, disconnect.
# Per-turn orchestration lives in app.services.agent_session.AgentSession.
import logging
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db_session
from app.repositories import ai_provider_repo
from app.schemas.base import AgentModelsResponse
from app.services.agent import AgentConnectionManager, send_event
from app.services.agent_session import AgentSession
from app.api.deps import CurrentUserWS, CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter()

manager = AgentConnectionManager()


@router.get("/agent/models", response_model=AgentModelsResponse)
async def list_models(user: CurrentUser, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    """Return the current default model and the user's custom-configured AI
    providers (so the frontend can populate the chat model picker with
    provider-grouped models).

    The "default" model is the first user-added provider's first model — we
    no longer fall back to the server-configured ``AI_MODEL`` (gpt-5.5) when
    the user has at least one provider configured. ``default_provider_id`` is
    returned alongside so the client knows which provider to bind to.
    """
    providers_raw, _ = await ai_provider_repo.list_for_user(
        db, user_id=user.id, active_only=True
    )
    providers = [
        {
            "id": str(p.id),
            "name": p.name,
            "base_url": p.base_url,
            "has_api_key": bool(p.api_key_encrypted),
            "models": list(p.models or []),
        }
        for p in providers_raw
    ]
    # Default = first active provider's first model. Falls back to the
    # server-configured default only when the user has no providers yet.
    default_model = settings.AI_MODEL
    default_provider_id: str | None = None
    if providers and providers[0]["models"]:
        default_provider_id = providers[0]["id"]
        default_model = providers[0]["models"][0]
    return {
        "default": default_model,
        "default_provider_id": default_provider_id,
        "models": [],
        "providers": providers,
    }


@router.websocket("/ws/agent")
async def agent_websocket(
    websocket: WebSocket,
    user: CurrentUserWS,
) -> None:
    if user is None:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(websocket)
    session = AgentSession(
        websocket,
        user,
    )

    try:
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            await session.handle_frame(data)
    finally:
        await session.shutdown()
        manager.disconnect(websocket)
