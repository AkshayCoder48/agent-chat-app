"""Hopx sandbox integration.

This module wraps the per-user workspace tools so that when a user has set
their HOPX_API_KEY (via Settings → Config), file/terminal ops are routed
through the Hopx REST API instead of the local per-user workspace.

When no Hopx key is set, the tools fall back to the local workspace (see
``app.agents.tools.workspace_tools``). The agent never sees the difference
— the tool signatures stay the same.

Hopx API surface used here (based on the public docs at https://docs.hopx.ai):
  POST /v1/sandboxes                   → create a sandbox (returns id + api_key)
  GET  /v1/sandboxes/{id}              → inspect a sandbox
  DELETE /v1/sandboxes/{id}            → tear down a sandbox
  GET  /v1/sandboxes/{id}/files        → list files (optional ?path=)
  POST /v1/sandboxes/{id}/files        → write a file (JSON {path, content})
  GET  /v1/sandboxes/{id}/files/{path} → read a file (text)
  DELETE /v1/sandboxes/{id}/files/{path} → delete a file
  POST /v1/sandboxes/{id}/exec         → run a shell command (returns stdout/stderr/exit_code)

The sandbox ID is cached per-WS-session in ``workspace_tools._HOPX_SESSION_CACHE``
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

# The Hopx production API host. Overridable via env so we can point at a
# staging host for testing without a code change.
HOPX_BASE_URL = settings.HOPX_BASE_URL if hasattr(settings, "HOPX_BASE_URL") else (
    "https://api.hopx.ai"
)


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


def _auth_headers(api_key: str) -> dict[str, str]:
    """Hopx accepts the user's API key as a Bearer token."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


async def hopx_create_sandbox(api_key: str) -> dict[str, Any] | None:
    """Create a fresh Hopx sandbox. Returns the sandbox metadata or None.

    The sandbox gets a 1-hour TTL by default — long enough for a chat turn,
    short enough that idle sandboxes don't accumulate cost.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{HOPX_BASE_URL}/v1/sandboxes",
                headers={**_auth_headers(api_key), "Content-Type": "application/json"},
                json={"ttl_seconds": 3600},
            )
            if resp.status_code >= 400:
                logger.warning(
                    "Hopx create-sandbox failed: %s %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return None
            data = resp.json()
            # Hopx may return {"id": "...", ...} or {"sandbox_id": "...", ...}
            # — accept either.
            if not (data.get("id") or data.get("sandbox_id")):
                logger.warning("Hopx create-sandbox returned no id: %s", data)
                return None
            return data
    except Exception:
        logger.warning("Hopx create-sandbox request failed", exc_info=True)
        return None


async def hopx_destroy_sandbox(api_key: str, sandbox_id: str) -> None:
    """Tear down a Hopx sandbox (best-effort)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.delete(
                f"{HOPX_BASE_URL}/v1/sandboxes/{sandbox_id}",
                headers=_auth_headers(api_key),
            )
    except Exception:
        # Best-effort — don't crash on shutdown.
        pass


async def hopx_list_files(
    api_key: str, sandbox_id: str, path: str = "."
) -> dict[str, Any] | None:
    """List files in a Hopx sandbox. Returns the raw response or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{HOPX_BASE_URL}/v1/sandboxes/{sandbox_id}/files",
                headers=_auth_headers(api_key),
                params={"path": path} if path and path != "." else None,
            )
            if resp.status_code >= 400:
                logger.debug(
                    "Hopx list-files %s returned %s", path, resp.status_code
                )
                return None
            return resp.json()
    except Exception:
        return None


async def hopx_read_file(api_key: str, sandbox_id: str, path: str) -> str | None:
    """Read a file's text content from a Hopx sandbox."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{HOPX_BASE_URL}/v1/sandboxes/{sandbox_id}/files/{path.lstrip('/')}",
                headers=_auth_headers(api_key),
            )
            if resp.status_code >= 400:
                logger.debug(
                    "Hopx read-file %s returned %s", path, resp.status_code
                )
                return None
            return resp.text
    except Exception:
        return None


async def hopx_write_file(
    api_key: str, sandbox_id: str, path: str, content: str
) -> bool:
    """Write text content to a file in a Hopx sandbox. Returns True on success."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{HOPX_BASE_URL}/v1/sandboxes/{sandbox_id}/files",
                headers={**_auth_headers(api_key), "Content-Type": "application/json"},
                json={"path": path, "content": content},
            )
            if resp.status_code >= 400:
                logger.warning(
                    "Hopx write-file %s failed: %s %s",
                    path,
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            return True
    except Exception:
        logger.warning("Hopx write-file request failed", exc_info=True)
        return False


async def hopx_delete_file(api_key: str, sandbox_id: str, path: str) -> bool:
    """Delete a file from a Hopx sandbox."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                f"{HOPX_BASE_URL}/v1/sandboxes/{sandbox_id}/files/{path.lstrip('/')}",
                headers=_auth_headers(api_key),
            )
            return resp.status_code < 400
    except Exception:
        return False


async def hopx_exec(
    api_key: str, sandbox_id: str, command: str, cwd: str = "."
) -> dict[str, Any] | None:
    """Run a shell command inside a Hopx sandbox.

    Returns ``{"stdout", "stderr", "exit_code"}`` on success, or
    ``{"error": "..."}`` on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{HOPX_BASE_URL}/v1/sandboxes/{sandbox_id}/exec",
                headers={**_auth_headers(api_key), "Content-Type": "application/json"},
                json={"command": command, "cwd": cwd},
            )
            if resp.status_code >= 400:
                return {
                    "error": f"Hopx exec failed: HTTP {resp.status_code}",
                    "stdout": "",
                    "stderr": resp.text[:500],
                    "exit_code": -1,
                }
            data = resp.json()
            # Normalise: Hopx may return {stdout, stderr, exit_code} or
            # {output, exit_code} (older API). Map both to the canonical shape.
            return {
                "stdout": data.get("stdout") or data.get("output") or "",
                "stderr": data.get("stderr") or "",
                "exit_code": data.get("exit_code", data.get("returncode", -1)),
            }
    except Exception as exc:
        return {
            "error": f"Hopx exec request failed: {exc}",
            "stdout": "",
            "stderr": str(exc),
            "exit_code": -1,
        }


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
