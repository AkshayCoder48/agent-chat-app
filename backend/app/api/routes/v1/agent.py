
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
            # Surface these so the WS client knows how to build the agent
            # for that provider (chat vs responses endpoint; tools on/off).
            "model_type": getattr(p, "model_type", None) or "chat",
            "tools_enabled": bool(getattr(p, "tools_enabled", True)),
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


@router.get("/agent/diagnose")
async def diagnose_provider(
    user: CurrentUser,
    provider_id: str,
    model: str | None = None,
) -> dict[str, Any]:
    """Test connectivity from the BACKEND HOST to a user-configured provider.

    This endpoint exists specifically to diagnose "Connection error." reports
    that surface in the chat UI. The chat itself runs over a WebSocket and
    the openai SDK collapses every network-level failure (DNS, TLS, connect
    timeout, IP block, RemoteProtocolError, …) into the bare string
    ``"Connection error."`` with no diagnostic detail.

    This endpoint does the same provider call the chat would do, but via a
    plain HTTP request whose response can carry the full exception type +
    cause chain + traceback excerpt. So when a user reports "Connection
    error." in the chat UI, hit this endpoint from the SAME host the
    backend runs on (e.g. ``curl https://api.example.com/api/v1/agent/diagnose?provider_id=...``)
    and you'll see exactly what the backend sees when it tries to reach
    the provider.

    Returns:
        ok: True if the provider responded with a non-error completion.
        provider_base_url, model, http_status: the request shape.
        error_type, error_message, cause_chain: populated when ok=False.
        completion: the model's reply (truncated) when ok=True.
    """
    import json as _json
    import traceback as _tb

    from app.agents.reasoning_transport import build_reasoning_aware_client

    db_session: AsyncSession | None = None
    try:
        async with get_db_session() as db:  # type: ignore[arg-type]
            prov = await ai_provider_repo.get_by_id(db, provider_id)
            if prov is None or prov.user_id != user.id:
                return {"ok": False, "error": "provider not found for current user"}
            base_url = prov.base_url
            api_key = (
                ai_provider_repo.get_decrypted_api_key(prov)
                if prov.api_key_encrypted
                else None
            )
            selected_model = model or (prov.models[0] if prov.models else "")
    except Exception as e:
        return {
            "ok": False,
            "error": f"failed to load provider: {type(e).__name__}: {e}",
        }

    if not selected_model:
        return {"ok": False, "error": "no model specified (provider has no models and ?model= not provided)"}

    # Build the EXACT same client the chat uses (ReasoningAwareTransport
    # + hardened httpx config). This way we're testing the real path.
    http_client = build_reasoning_aware_client(
        base_url=base_url,
        api_key=api_key or "unset",
    )

    # Send a one-token streaming chat-completion request. Streaming is
    # important — most of the "Connection error." failures happen DURING
    # the SSE stream (mid-chunk network drop, malformed chunk, etc.), not
    # during the initial HTTP handshake.
    try:
        async with http_client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": selected_model,
                "messages": [{"role": "user", "content": "Say pong and nothing else."}],
                "stream": True,
                "max_tokens": 16,
            },
            timeout=30.0,
        ) as resp:
            status = resp.status_code
            ct = resp.headers.get("content-type", "")
            chunks: list[str] = []
            total_bytes = 0
            async for raw in resp.aiter_bytes():
                total_bytes += len(raw)
                # Capture first 5 SSE events for the response payload
                if len(chunks) < 5:
                    try:
                        text = raw.decode("utf-8", errors="replace")
                        chunks.append(text[:400])
                    except Exception:
                        chunks.append(f"<{len(raw)} bytes>")
                if total_bytes > 8192:
                    break
            return {
                "ok": 200 <= status < 300,
                "provider_base_url": base_url,
                "model": selected_model,
                "http_status": status,
                "content_type": ct,
                "bytes_received": total_bytes,
                "first_chunks": chunks,
            }
    except Exception as e:
        # Walk the cause chain — same logic as _format_agent_error
        chain: list[str] = []
        cur: BaseException | None = e
        while cur is not None and len(chain) < 8:
            chain.append(f"{type(cur).__name__}: {str(cur)[:200] or '(no message)'}")
            cur = cur.__cause__ or cur.__context__
        return {
            "ok": False,
            "provider_base_url": base_url,
            "model": selected_model,
            "error_type": type(e).__name__,
            "error_message": str(e),
            "cause_chain": chain,
            "traceback_excerpt": _tb.format_exc()[-2000:],
        }
