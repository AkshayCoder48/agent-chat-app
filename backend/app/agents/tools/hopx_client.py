"""Hopx sandbox integration.

This module wraps the per-user workspace tools so that when a user has set
their HOPX_API_KEY (via Settings → Config), file/terminal ops are routed
through the Hopx REST API instead of the local per-user workspace.

When no Hopx key is set, the tools fall back to the local workspace (see
``app.agents.tools.workspace_tools``). The agent never sees the difference
— the tool signatures stay the same.

Hopx API surface used here:
  POST /v1/sandboxes                 → create a sandbox (returns sandbox_id + api_key)
  POST /v1/sandboxes/{id}/files      → upload a file (multipart)
  GET  /v1/sandboxes/{id}/files/{path} → download a file
  GET  /v1/sandboxes/{id}/files      → list files
  DELETE /v1/sandboxes/{id}/files/{path} → delete a file
  POST /v1/sandboxes/{id}/exec       → run a command (returns stdout/stderr/exit_code)
  DELETE /v1/sandboxes/{id}          → tear down the sandbox

The sandbox ID is cached per-WS-session in ``AgentSession._hopx_sandbox_id``
so we don't pay the create-sandbox cost on every tool call. The sandbox is
torn down on ``shutdown()``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

import httpx

from app.core.config import settings
from app.db.session import get_db_context
from app.core.crypto import decrypt_value

logger = logging.getLogger(__name__)

HOPX_BASE_URL = "https://api.hopx.ai"  # adjust when the SDK publishes the prod URL


async def get_user_hopx_key(user_id: UUID | str) -> str | None:
    """Return the user's decrypted Hopx API key, or None when not set."""
    try:
        from app.db.models.user_settings import UserSettings
        from sqlalchemy import select

        async with get_db_context() as db:
            row = (
                await db.execute(
                    select(UserSettings).where(UserSettings.user_id == UUID(str(user_id)))
                )
            ).scalar_one_or_none()
            if row is None or not row.hopx_api_key_encrypted:
                return None
            col = row.hopx_api_key_encrypted
            if col.startswith("plain::"):
                return col[len("plain::") :]
            try:
                return decrypt_value(col, settings.SECRET_KEY)
            except Exception:
                return None
    except Exception:
        logger.warning("Failed to load Hopx API key", exc_info=True)
        return None


async def hopx_create_sandbox(api_key: str) -> dict[str, Any] | None:
    """Create a fresh Hopx sandbox. Returns the sandbox metadata or None."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{HOPX_BASE_URL}/v1/sandboxes",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"ttl_seconds": 3600},
            )
            if resp.status_code >= 400:
                logger.warning("Hopx create-sandbox failed: %s %s", resp.status_code, resp.text[:200])
                return None
            return resp.json()
    except Exception:
        logger.warning("Hopx create-sandbox request failed", exc_info=True)
        return None


async def hopx_destroy_sandbox(api_key: str, sandbox_id: str) -> None:
    """Tear down a Hopx sandbox (best-effort)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.delete(
                f"{HOPX_BASE_URL}/v1/sandboxes/{sandbox_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except Exception:
        # Best-effort — don't crash on shutdown.
        pass


async def hopx_list_files(api_key: str, sandbox_id: str, path: str = ".") -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{HOPX_BASE_URL}/v1/sandboxes/{sandbox_id}/files",
                headers={"Authorization": f"Bearer {api_key}"},
                params={"path": path},
            )
            if resp.status_code >= 400:
                return None
            return resp.json()
    except Exception:
        return None


async def hopx_read_file(api_key: str, sandbox_id: str, path: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{HOPX_BASE_URL}/v1/sandboxes/{sandbox_id}/files/{path.lstrip('/')}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code >= 400:
                return None
            return resp.text
    except Exception:
        return None


async def hopx_write_file(
    api_key: str, sandbox_id: str, path: str, content: str
) -> bool:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{HOPX_BASE_URL}/v1/sandboxes/{sandbox_id}/files",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"path": path, "content": content},
            )
            return resp.status_code < 400
    except Exception:
        return False


async def hopx_delete_file(api_key: str, sandbox_id: str, path: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                f"{HOPX_BASE_URL}/v1/sandboxes/{sandbox_id}/files/{path.lstrip('/')}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            return resp.status_code < 400
    except Exception:
        return False


async def hopx_exec(
    api_key: str, sandbox_id: str, command: str, cwd: str = "."
) -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{HOPX_BASE_URL}/v1/sandboxes/{sandbox_id}/exec",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"command": command, "cwd": cwd},
            )
            if resp.status_code >= 400:
                return {"error": f"Hopx exec failed: HTTP {resp.status_code}"}
            return resp.json()
    except Exception as exc:
        return {"error": f"Hopx exec request failed: {exc}"}


__all__ = [
    "get_user_hopx_key",
    "hopx_create_sandbox",
    "hopx_destroy_sandbox",
    "hopx_list_files",
    "hopx_read_file",
    "hopx_write_file",
    "hopx_delete_file",
    "hopx_exec",
    "HOPX_BASE_URL",
]
