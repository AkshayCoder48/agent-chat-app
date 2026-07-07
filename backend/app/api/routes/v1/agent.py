
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

    Note: we intentionally do NOT return the server's built-in
    ``AI_AVAILABLE_MODELS`` list — the chat picker should show only models
    the user has explicitly added via Settings → Config. The default model
    name is still returned so the picker can label the "use server default"
    option.
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
    return {
        "default": settings.AI_MODEL,
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
