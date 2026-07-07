"""Environment-variable tools the AI can call to manage the user's env vars.

Three tools are exposed (registered in :mod:`app.agents.assistant`):

  * ``set_env``    — create a new env var (or update if it already exists)
  * ``delete_env`` — remove an env var
  * ``list_env``   — list the names of the user's env vars (values are masked
                     for secrets; plain values are returned in full)

These tools let the AI collaboratively manage credentials during a chat —
e.g. the user says "save my OpenAI key as OPENAI_API_KEY", the AI calls
``set_env(name="OPENAI_API_KEY", value="sk-…", is_secret=True)``.

When the user has a Hopx API key set, every mutation also rewrites the
``.env`` file inside their Hopx sandbox so the AI can read it via
``read_file(".env")`` when running code on the user's behalf.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.routes.v1.env_vars import (
    _dec,
    _enc,
    _get_or_create,
    _sync_to_hopx,
)
from app.db.session import get_db_context

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


class SetEnvArgs(BaseModel):
    name: str = Field(
        ...,
        description="The env var name (UPPER_SNAKE_CASE: A-Z, 0-9, _; must start with letter or _).",
    )
    value: str = Field(..., description="The env var value.")
    is_secret: bool = Field(
        default=True,
        description="Whether the value should be masked in the UI. Default true.",
    )


class DeleteEnvArgs(BaseModel):
    name: str = Field(..., description="The env var name to delete.")


async def set_env(user_id: str | UUID, args: SetEnvArgs) -> dict[str, Any]:
    """Create or update an env var. Idempotent — if the var exists, it's overwritten."""
    name = args.name.strip().upper()
    if not _NAME_RE.match(name):
        return {
            "ok": False,
            "error": "Name must be UPPER_SNAKE_CASE (A-Z, 0-9, _; start with letter or _).",
        }
    if not args.value:
        return {"ok": False, "error": "Value must not be empty."}

    try:
        from datetime import datetime, timezone

        async with get_db_context() as db:
            row = await _get_or_create(db, UUID(str(user_id)))
            env_dict = dict(row.env_vars or {})
            existing = env_dict.get(name, {})
            stored_value = _enc(args.value) if args.is_secret else args.value
            now = datetime.now(timezone.utc).isoformat()
            env_dict[name] = {
                "value": stored_value,
                "is_secret": args.is_secret,
                "created_at": existing.get("created_at", now),
                "updated_at": now,
            }
            row.env_vars = env_dict
            await db.flush()

            # Sync the decrypted env to Hopx.
            plain_env = {
                k: _dec(v["value"]) if v.get("is_secret") else v["value"]
                for k, v in env_dict.items()
            }
        hopx_synced = await _sync_to_hopx(UUID(str(user_id)), plain_env)

        return {
            "ok": True,
            "name": name,
            "is_secret": args.is_secret,
            "hopx_synced": hopx_synced,
            "message": (
                f"Saved {name}." + (" Synced to Hopx .env file." if hopx_synced else "")
            ),
        }
    except Exception as exc:
        logger.warning("set_env failed", exc_info=True)
        return {"ok": False, "error": f"Failed to set env: {exc}"}


async def delete_env(user_id: str | UUID, args: DeleteEnvArgs) -> dict[str, Any]:
    """Remove an env var by name."""
    name = args.name.strip().upper()
    if not _NAME_RE.match(name):
        return {"ok": False, "error": "Invalid name."}

    try:
        async with get_db_context() as db:
            row = await _get_or_create(db, UUID(str(user_id)))
            env_dict = dict(row.env_vars or {})
            if name not in env_dict:
                return {"ok": False, "error": f"Env var {name} not found."}
            env_dict.pop(name)
            row.env_vars = env_dict
            await db.flush()

            plain_env = {
                k: _dec(v["value"]) if v.get("is_secret") else v["value"]
                for k, v in env_dict.items()
            }
        hopx_synced = await _sync_to_hopx(UUID(str(user_id)), plain_env)

        return {
            "ok": True,
            "name": name,
            "hopx_synced": hopx_synced,
            "message": (
                f"Deleted {name}." + (" Hopx .env re-synced." if hopx_synced else "")
            ),
        }
    except Exception as exc:
        logger.warning("delete_env failed", exc_info=True)
        return {"ok": False, "error": f"Failed to delete env: {exc}"}


async def list_env(user_id: str | UUID) -> dict[str, Any]:
    """List the user's env vars. Secret values are masked; plain values are shown."""
    try:
        from app.api.routes.v1.env_vars import _mask

        async with get_db_context() as db:
            row = await _get_or_create(db, UUID(str(user_id)))
            env_dict = dict(row.env_vars or {})

        items = []
        for name, meta in sorted(env_dict.items()):
            if not isinstance(meta, dict):
                continue
            is_secret = bool(meta.get("is_secret", True))
            stored = str(meta.get("value", ""))
            display = _mask(_dec(stored)) if is_secret and stored else (stored if not is_secret else "")
            items.append({"name": name, "value": display, "is_secret": is_secret})

        return {"ok": True, "vars": items, "count": len(items)}
    except Exception as exc:
        logger.warning("list_env failed", exc_info=True)
        return {"ok": False, "error": f"Failed to list env: {exc}"}


__all__ = ["SetEnvArgs", "DeleteEnvArgs", "set_env", "delete_env", "list_env"]
