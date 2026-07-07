"""Environment-variable endpoints for the per-user sandbox.

Each user has a JSONB ``env_vars`` column on their ``UserSettings`` row. Values
marked ``is_secret=True`` are encrypted at rest; the GET endpoint never
returns the raw secret value — it returns a masked placeholder so the UI can
show that a secret exists without leaking it.

When the user has a Hopx API key set, every mutation also rewrites the
``.env`` file inside their Hopx sandbox so the AI can read it when running
code on the user's behalf. The first mutation triggers a one-time sandbox
creation (the per-session cache lives in ``workspace_tools``).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
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
router = APIRouter(prefix="/agent-settings/env-vars", tags=["agent-settings:env-vars"])

# UPPER_SNAKE_CASE — what shells, dotenv and most tools expect.
_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


class EnvVarItem(BaseModel):
    name: str
    value: str  # masked for secrets; raw for plain
    is_secret: bool
    created_at: str | None = None
    updated_at: str | None = None


class EnvVarListResponse(BaseModel):
    vars: list[EnvVarItem]
    hopx_synced: bool


class EnvVarCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    value: str = Field(..., min_length=1)
    is_secret: bool = True


class EnvVarUpdate(BaseModel):
    value: str = Field(..., min_length=1)
    is_secret: bool | None = None


class EnvVarOpResponse(BaseModel):
    ok: bool = True
    name: str
    hopx_synced: bool = False
    message: str | None = None


async def _get_or_create(db: AsyncSession, user_id: UUID) -> UserSettings:
    stmt = select(UserSettings).where(UserSettings.user_id == user_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = UserSettings(user_id=user_id)
        db.add(row)
        await db.flush()
    return row


def _enc(value: str) -> str:
    """Encrypt a value, falling back to plain:: prefix if crypto fails."""
    try:
        return encrypt_value(value, settings.SECRET_KEY)
    except Exception:
        return f"plain::{value}"


def _dec(stored: str) -> str:
    """Decrypt a value (inverse of :func:`_enc`)."""
    if stored.startswith("plain::"):
        return stored[len("plain::") :]
    try:
        return decrypt_value(stored, settings.SECRET_KEY)
    except Exception:
        return ""


def _mask(value: str) -> str:
    """Return a masked placeholder of similar length (for the GET endpoint)."""
    if not value:
        return ""
    n = max(8, min(24, len(value)))
    return "•" * n


async def _sync_to_hopx(user_id: UUID, env_dict: dict[str, str]) -> bool:
    """Write the env vars as a .env file in the user's Hopx sandbox.

    Returns True when synced, False when no Hopx key is set or the sync
    failed (best-effort — the DB write still succeeds).
    """
    try:
        from app.agents.tools.hopx_client import get_user_hopx_key
        from app.agents.tools.workspace_tools import _get_hopx_session, _HOPX_SESSION_CACHE
        from app.agents.tools.hopx_client import hopx_write_file

        api_key = await get_user_hopx_key(user_id)
        if not api_key:
            return False

        session = await _get_hopx_session(user_id)
        if session is None:
            return False

        # Build a dotenv file: KEY=value, one per line. Secrets and plain
        # values are written the same way — the file is only readable inside
        # the user's own sandbox.
        lines = [f"{k}={v}" for k, v in sorted(env_dict.items())]
        content = "\n".join(lines) + ("\n" if lines else "")
        ok = await hopx_write_file(
            session["api_key"], session["sandbox_id"], ".env", content
        )
        return bool(ok)
    except Exception:
        logger.warning("Hopx .env sync failed", exc_info=True)
        return False


@router.get("", response_model=EnvVarListResponse)
async def list_env_vars(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """List the user's env vars. Secret values are masked."""
    row = await _get_or_create(db, current_user.id)
    raw = dict(row.env_vars or {})
    out: list[EnvVarItem] = []
    for name, meta in raw.items():
        if not isinstance(meta, dict):
            continue
        is_secret = bool(meta.get("is_secret", True))
        stored_value = str(meta.get("value", ""))
        if is_secret:
            display = _mask(_dec(stored_value)) if stored_value else ""
        else:
            display = stored_value
        out.append(
            EnvVarItem(
                name=name,
                value=display,
                is_secret=is_secret,
                created_at=meta.get("created_at"),
                updated_at=meta.get("updated_at"),
            )
        )
    # Sort alphabetically by name for stable display.
    out.sort(key=lambda v: v.name)
    # Hopx is considered "synced" if the user has a key set AND we have a
    # cached sandbox session for them (i.e. they've used the agent at least
    # once with Hopx enabled). We don't ping Hopx here to avoid latency.
    hopx_synced = False
    try:
        from app.agents.tools.hopx_client import get_user_hopx_key
        from app.agents.tools.workspace_tools import _HOPX_SESSION_CACHE

        if await get_user_hopx_key(current_user.id):
            hopx_synced = str(current_user.id) in _HOPX_SESSION_CACHE
    except Exception:
        pass
    return EnvVarListResponse(vars=out, hopx_synced=hopx_synced)


@router.post("", response_model=EnvVarOpResponse, status_code=201)
async def create_env_var(
    payload: EnvVarCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Add a new env var. Refuses to clobber an existing name."""
    name = payload.name.strip().upper()
    if not _NAME_RE.match(name):
        raise HTTPException(400, "Name must be UPPER_SNAKE_CASE (A-Z, 0-9, _)")

    row = await _get_or_create(db, current_user.id)
    env_dict = dict(row.env_vars or {})
    if name in env_dict:
        raise HTTPException(409, f"Env var {name!r} already exists — use PUT to update")

    now = datetime.now(timezone.utc).isoformat()
    stored_value = _enc(payload.value) if payload.is_secret else payload.value
    env_dict[name] = {
        "value": stored_value,
        "is_secret": payload.is_secret,
        "created_at": now,
        "updated_at": now,
    }
    row.env_vars = env_dict
    await db.flush()

    # Sync the decrypted env to Hopx (so the AI can read it via .env).
    plain_env = {k: _dec(v["value"]) if v.get("is_secret") else v["value"] for k, v in env_dict.items()}
    hopx_synced = await _sync_to_hopx(current_user.id, plain_env)

    return EnvVarOpResponse(
        name=name,
        hopx_synced=hopx_synced,
        message="Synced to Hopx .env" if hopx_synced else None,
    )


@router.put("/{name}", response_model=EnvVarOpResponse)
async def update_env_var(
    name: str,
    payload: EnvVarUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Update an existing env var's value (and optionally its secret flag)."""
    name = name.strip().upper()
    if not _NAME_RE.match(name):
        raise HTTPException(400, "Name must be UPPER_SNAKE_CASE (A-Z, 0-9, _)")

    row = await _get_or_create(db, current_user.id)
    env_dict = dict(row.env_vars or {})
    if name not in env_dict:
        raise HTTPException(404, f"Env var {name!r} not found")

    existing = env_dict[name]
    is_secret = payload.is_secret if payload.is_secret is not None else bool(
        existing.get("is_secret", True)
    )
    stored_value = _enc(payload.value) if is_secret else payload.value
    env_dict[name] = {
        "value": stored_value,
        "is_secret": is_secret,
        "created_at": existing.get("created_at"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    row.env_vars = env_dict
    await db.flush()

    plain_env = {k: _dec(v["value"]) if v.get("is_secret") else v["value"] for k, v in env_dict.items()}
    hopx_synced = await _sync_to_hopx(current_user.id, plain_env)

    return EnvVarOpResponse(
        name=name,
        hopx_synced=hopx_synced,
        message="Synced to Hopx .env" if hopx_synced else None,
    )


@router.delete("/{name}", response_model=EnvVarOpResponse)
async def delete_env_var(
    name: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Remove an env var."""
    name = name.strip().upper()
    row = await _get_or_create(db, current_user.id)
    env_dict = dict(row.env_vars or {})
    if name not in env_dict:
        raise HTTPException(404, f"Env var {name!r} not found")
    env_dict.pop(name)
    row.env_vars = env_dict
    await db.flush()

    plain_env = {k: _dec(v["value"]) if v.get("is_secret") else v["value"] for k, v in env_dict.items()}
    hopx_synced = await _sync_to_hopx(current_user.id, plain_env)

    return EnvVarOpResponse(
        name=name,
        hopx_synced=hopx_synced,
        message="Synced to Hopx .env" if hopx_synced else None,
    )


async def get_user_env_vars(user_id: UUID | str) -> dict[str, str]:
    """Return the user's env vars as a plain {name: value} dict.

    Used by the agent's env-tools and the code-execution tool to inject
    credentials into the sandbox. Decrypts secret values on the fly.
    """
    from app.db.session import get_db_context

    try:
        async with get_db_context() as db:
            row = await _get_or_create(db, UUID(str(user_id)))
            env_dict = dict(row.env_vars or {})
            return {
                name: _dec(meta["value"]) if meta.get("is_secret") else str(meta.get("value", ""))
                for name, meta in env_dict.items()
                if isinstance(meta, dict)
            }
    except Exception:
        logger.warning("Failed to load user env vars", exc_info=True)
        return {}


__all__ = ["router", "get_user_env_vars"]
