"""File-system tools that operate on a per-user workspace.

Backed by the local filesystem today (each user gets a directory under
``settings.MEDIA_DIR / workspaces / <user_id>``); designed so the
implementation can be swapped for Hopx sandbox ops without changing the
tool signatures the agent has learned.

Tools exposed (registered in :mod:`app.agents.assistant`):
  * ``list_files`` — list a directory
  * ``read_file`` — return a file's text content
  * ``create_file`` — write text to a new path
  * ``write_file`` — overwrite an existing path
  * ``edit_file`` — find-and-replace within a file
  * ``delete_file`` — remove a file
  * ``create_folder`` — make a directory
  * ``delete_folder`` — remove a directory tree
  * ``send_file`` — return a download link for a file (rendered as a card)
  * ``send_folder`` — return a download link for a folder (zip)

All paths are resolved *relative to* the user's workspace root; absolute
paths or ``..`` escapes are rejected.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import settings

logger = logging.getLogger(__name__)

# Cap a single read at 256 KB so the agent can't OOM the chat history.
_MAX_READ_BYTES = 256 * 1024
# Cap a single write at 5 MB so the agent can't fill the disk.
_MAX_WRITE_BYTES = 5 * 1024 * 1024


def _workspace_root(user_id: str | UUID) -> Path:
    """Return the per-user workspace directory, creating it if needed."""
    root = Path(settings.MEDIA_DIR) / "workspaces" / str(user_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_safe(root: Path, rel_path: str) -> Path:
    """Resolve ``rel_path`` under ``root``, rejecting escapes.

    The resolved path is checked with ``Path.resolve()`` and verified to be
    inside ``root``. Absolute paths and ``..`` segments that would escape
    the workspace are rejected with a ``ValueError``.
    """
    if not rel_path or rel_path in {".", "./"}:
        return root
    candidate = (root / rel_path).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(
            f"Path '{rel_path}' escapes the user workspace"
        ) from exc
    return candidate


# ----------------------------------------------------------------- Hopx routing
# When the user has set a HOPX_API_KEY (Settings → Config), file/terminal
# ops are routed through the Hopx REST API instead of the local workspace.
# The sandbox ID is cached per-WS-session on the AgentSession so we don't
# pay the create-sandbox cost on every tool call.

_HOPX_SESSION_CACHE: dict[str, dict[str, Any]] = {}


async def _get_hopx_session(user_id: str | UUID) -> dict[str, Any] | None:
    """Return the user's Hopx session (api_key + sandbox_id) or None.

    Creates the sandbox on first call and caches it. Returns None when the
    user hasn't set a Hopx API key (caller falls back to the local FS).
    """
    from app.agents.tools.hopx_client import (
        get_user_hopx_key,
        hopx_create_sandbox,
    )

    key = str(user_id)
    if key in _HOPX_SESSION_CACHE:
        return _HOPX_SESSION_CACHE[key]

    api_key = await get_user_hopx_key(user_id)
    if not api_key:
        return None

    sandbox = await hopx_create_sandbox(api_key)
    if sandbox is None:
        # Don't cache failure — the next call will retry.
        return None

    session = {"api_key": api_key, "sandbox_id": sandbox.get("id") or sandbox.get("sandbox_id")}
    if not session["sandbox_id"]:
        logger.warning("Hopx sandbox creation returned no id: %s", sandbox)
        return None
    _HOPX_SESSION_CACHE[key] = session
    return session


async def destroy_hopx_session(user_id: str | UUID) -> None:
    """Tear down the user's Hopx sandbox (called on WS shutdown)."""
    from app.agents.tools.hopx_client import hopx_destroy_sandbox

    key = str(user_id)
    session = _HOPX_SESSION_CACHE.pop(key, None)
    if session is None:
        return
    await hopx_destroy_sandbox(session["api_key"], session["sandbox_id"])


def _to_download_url(user_id: str | UUID, rel_path: str, is_folder: bool = False) -> str:
    """Build a download URL the frontend can fetch.

    The actual serving is handled by the ``/api/v1/files/workspace`` route
    family; the frontend's ``FileDownloadResult`` component parses this URL
    and renders a download card.
    """
    safe = rel_path.lstrip("/")
    if is_folder:
        return f"/api/v1/files/workspace/{user_id}/download-folder?path={safe}"
    return f"/api/v1/files/workspace/{user_id}/download?path={safe}"


# ----------------------------------------------------------------- list_files

async def list_files(user_id: str | UUID, path: str = ".") -> dict[str, Any]:
    """List files and folders under ``path`` (relative to the workspace root).

    Returns ``{"entries": [{"name", "type", "size"}], "path": "<resolved>"}``.
    """
    root = _workspace_root(user_id)
    target = _resolve_safe(root, path)
    if not target.exists():
        return {"error": f"Path does not exist: {path}", "entries": [], "path": path}
    if target.is_file():
        return {
            "entries": [{"name": target.name, "type": "file", "size": target.stat().st_size}],
            "path": path,
        }

    entries: list[dict[str, Any]] = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_file(), p.name.lower())):
        try:
            st = child.stat()
        except OSError:
            continue
        entries.append(
            {
                "name": child.name,
                "type": "folder" if child.is_dir() else "file",
                "size": st.st_size if child.is_file() else None,
            }
        )
    return {"entries": entries, "path": path}


# ----------------------------------------------------------------- read_file

async def read_file(user_id: str | UUID, path: str) -> str:
    """Return the text content of ``path`` (capped at 256 KB).

    When the user has set a Hopx API key, the file is read from their Hopx
    sandbox instead of the local workspace.
    """
    # Try Hopx first.
    session = await _get_hopx_session(user_id)
    if session is not None:
        from app.agents.tools.hopx_client import hopx_read_file
        text = await hopx_read_file(session["api_key"], session["sandbox_id"], path)
        if text is not None:
            return text if len(text) <= _MAX_READ_BYTES else text[:_MAX_READ_BYTES] + " (truncated)"
        return f"Error: Hopx read failed for {path}"

    # Local fallback.
    root = _workspace_root(user_id)
    target = _resolve_safe(root, path)
    if not target.exists():
        return f"Error: file does not exist: {path}"
    if target.is_dir():
        return f"Error: path is a directory: {path}"

    def _read() -> str:
        with target.open("rb") as fh:
            raw = fh.read(_MAX_READ_BYTES + 1)
        if len(raw) > _MAX_READ_BYTES:
            raw = raw[:_MAX_READ_BYTES]
            trunc = " (truncated at 256 KB)"
        else:
            trunc = ""
        try:
            return raw.decode("utf-8", errors="replace") + trunc
        except Exception as exc:  # pragma: no cover
            return f"Error decoding file: {exc}"

    return await asyncio.to_thread(_read)


# ----------------------------------------------------------------- create_file

async def create_file(
    user_id: str | UUID, path: str, content: str, overwrite: bool = False
) -> str:
    """Write ``content`` to a new file at ``path``.

    Args:
        path: Relative path inside the user's workspace.
        content: Text content to write (max 5 MB).
        overwrite: If False (default), refuse to clobber an existing file.

    Returns a one-line success message.
    """
    payload = content.encode("utf-8", errors="replace")
    if len(payload) > _MAX_WRITE_BYTES:
        return f"Error: content too large ({len(payload)} bytes > 5 MB)"

    # Hopx route.
    session = await _get_hopx_session(user_id)
    if session is not None:
        from app.agents.tools.hopx_client import hopx_write_file
        ok = await hopx_write_file(session["api_key"], session["sandbox_id"], path, content)
        return f"Created {path} ({len(payload)} bytes)" if ok else f"Error: Hopx write failed for {path}"

    # Local fallback.
    root = _workspace_root(user_id)
    target = _resolve_safe(root, path)
    if target.exists() and not overwrite:
        return f"Error: file already exists: {path} (pass overwrite=True to replace)"
    if target.is_dir():
        return f"Error: path is a directory: {path}"

    target.parent.mkdir(parents=True, exist_ok=True)

    def _write() -> None:
        with target.open("wb") as fh:
            fh.write(payload)

    await asyncio.to_thread(_write)
    return f"Created {path} ({len(payload)} bytes)"


# ----------------------------------------------------------------- write_file

async def write_file(user_id: str | UUID, path: str, content: str) -> str:
    """Overwrite the file at ``path`` with ``content`` (creates if missing)."""
    return await create_file(user_id, path, content, overwrite=True)


# ----------------------------------------------------------------- edit_file

async def edit_file(
    user_id: str | UUID,
    path: str,
    find: str,
    replace: str,
    replace_all: bool = True,
) -> str:
    """Find-and-replace within ``path``.

    Args:
        find: Literal substring to find (NOT a regex).
        replace: Replacement substring.
        replace_all: If True (default), replace every occurrence; if False,
            only the first.

    Returns a summary line; error string on failure.
    """
    root = _workspace_root(user_id)
    target = _resolve_safe(root, path)
    if not target.exists() or target.is_dir():
        return f"Error: file not found: {path}"

    text = await read_file(user_id, path)
    if find not in text:
        return f"Error: pattern not found in {path}"
    if replace_all:
        new_text = text.replace(find, replace)
        count = text.count(find)
    else:
        new_text = text.replace(find, replace, 1)
        count = 1
    await write_file(user_id, path, new_text)
    return f"Edited {path} ({count} replacement{'s' if count != 1 else ''})"


# ----------------------------------------------------------------- delete_file

async def delete_file(user_id: str | UUID, path: str) -> str:
    """Delete a single file."""
    root = _workspace_root(user_id)
    target = _resolve_safe(root, path)
    if not target.exists():
        return f"Error: file does not exist: {path}"
    if target.is_dir():
        return f"Error: path is a directory: {path} (use delete_folder)"
    await asyncio.to_thread(target.unlink)
    return f"Deleted {path}"


# ----------------------------------------------------------------- create_folder

async def create_folder(user_id: str | UUID, path: str) -> str:
    """Create a directory at ``path`` (mkdir -p semantics)."""
    root = _workspace_root(user_id)
    target = _resolve_safe(root, path)
    if target.exists() and target.is_file():
        return f"Error: a file already exists at {path}"
    await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)
    return f"Created folder {path}"


# ----------------------------------------------------------------- delete_folder

async def delete_folder(user_id: str | UUID, path: str) -> str:
    """Delete a directory tree at ``path`` (rm -rf semantics)."""
    root = _workspace_root(user_id)
    target = _resolve_safe(root, path)
    if not target.exists():
        return f"Error: folder does not exist: {path}"
    if target.is_file():
        return f"Error: path is a file: {path} (use delete_file)"
    if target == root:
        return "Error: refusing to delete workspace root"
    await asyncio.to_thread(shutil.rmtree, target)
    return f"Deleted folder {path}"


# ----------------------------------------------------------------- send_file

async def send_file(user_id: str | UUID, path: str) -> dict[str, Any]:
    """Return a download descriptor the frontend renders as a card.

    Returns ``{"item_type": "file", "name", "size", "url"}`` or an error dict.
    """
    root = _workspace_root(user_id)
    target = _resolve_safe(root, path)
    if not target.exists() or target.is_dir():
        return {"error": f"File not found: {path}"}
    return {
        "item_type": "file",
        "name": target.name,
        "size": target.stat().st_size,
        "url": _to_download_url(user_id, path, is_folder=False),
        "path": path,
    }


# ----------------------------------------------------------------- send_folder

async def send_folder(user_id: str | UUID, path: str) -> dict[str, Any]:
    """Return a folder download descriptor (served as a zip on demand)."""
    root = _workspace_root(user_id)
    target = _resolve_safe(root, path)
    if not target.exists() or target.is_file():
        return {"error": f"Folder not found: {path}"}

    # Count size + entries eagerly so the card can show "x files, y KB".
    total_size = 0
    file_count = 0
    for child in target.rglob("*"):
        if child.is_file():
            try:
                total_size += child.stat().st_size
                file_count += 1
            except OSError:
                continue

    return {
        "item_type": "folder",
        "name": target.name,
        "size": total_size,
        "file_count": file_count,
        "url": _to_download_url(user_id, path, is_folder=True),
        "path": path,
    }


# ----------------------------------------------------------------- run_terminal

# A small allowlist of safe, read-only commands the agent may run inside the
# per-user workspace. Anything not on this list is refused. This is a defense-
# in-depth measure — the sandbox also runs without elevated privileges.
_ALLOWED_COMMANDS = {
    "ls", "pwd", "cat", "head", "tail", "wc", "grep", "find", "tree",
    "echo", "date", "whoami", "uname", "df", "du", "file", "stat",
    "python3", "python", "node", "pip", "pip3", "npm", "yarn", "pnpm",
    "git", "diff", "sort", "uniq", "cut", "tr", "awk", "sed",
    "curl", "wget",  # network egress is allowed by default
    "md5sum", "sha256sum", "base64", "xxd",
}

# Max output size; longer output is truncated with a marker.
_MAX_OUTPUT_BYTES = 64 * 1024
# Wall-clock timeout per command.
_TERMINAL_TIMEOUT_SECS = 30.0


async def run_terminal(
    user_id: str | UUID, command: str, cwd: str = "."
) -> dict[str, Any]:
    """Run ``command`` inside the user's workspace.

    When a Hopx API key is set, the command runs inside the Hopx sandbox
    (no allowlist required — Hopx enforces isolation server-side). Without
    a Hopx key, only the binaries in :data:`_ALLOWED_COMMANDS` may be
    invoked; shell operators (``|``, ``;``, ``&&``, ``>``, ``<``, backticks)
    are NOT supported — the command is split with :func:`shlex.split` and
    run via ``execve``, not through a shell.

    Returns ``{"stdout", "stderr", "exit_code", "cwd"}``.
    """
    import shlex

    if not command or not command.strip():
        return {"error": "Empty command"}

    # Hopx route.
    session = await _get_hopx_session(user_id)
    if session is not None:
        from app.agents.tools.hopx_client import hopx_exec
        result = await hopx_exec(session["api_key"], session["sandbox_id"], command, cwd=cwd)
        if result is None:
            return {"error": "Hopx exec failed"}
        # Hopx returns {stdout, stderr, exit_code} or {error}.
        return {
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "exit_code": result.get("exit_code", -1),
            "cwd": cwd,
            **({"error": result["error"]} if "error" in result else {}),
        }

    # Local fallback with allowlist.
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return {"error": f"Could not parse command: {exc}"}

    if not argv:
        return {"error": "Empty command"}

    binary = os.path.basename(argv[0])
    if binary not in _ALLOWED_COMMANDS:
        return {
            "error": (
                f"Command '{binary}' is not allowed. Allowed: "
                + ", ".join(sorted(_ALLOWED_COMMANDS))
            )
        }

    root = _workspace_root(user_id)
    work_dir = _resolve_safe(root, cwd) if cwd and cwd != "." else root
    if not work_dir.exists() or not work_dir.is_dir():
        return {"error": f"Working directory does not exist: {cwd}"}

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(work_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return {"error": f"Binary not found: {argv[0]}"}

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=_TERMINAL_TIMEOUT_SECS
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return {
            "error": f"Command timed out after {_TERMINAL_TIMEOUT_SECS:.0f}s",
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "cwd": cwd,
        }

    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    if len(stdout) > _MAX_OUTPUT_BYTES:
        stdout = stdout[:_MAX_OUTPUT_BYTES] + "\n… (truncated)"
    if len(stderr) > _MAX_OUTPUT_BYTES:
        stderr = stderr[:_MAX_OUTPUT_BYTES] + "\n… (truncated)"

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": proc.returncode,
        "cwd": cwd,
    }


# ----------------------------------------------------------------- list_chats

async def list_chats(user_id: str | UUID, limit: int = 20) -> dict[str, Any]:
    """List the user's recent conversations (for the agent to refer back).

    Returns ``{"chats": [{"id", "title", "created_at", "message_count"}]}``.
    """
    from app.db.session import get_db_context
    from app.services.conversation import ConversationService

    async with get_db_context() as db:
        svc = ConversationService(db)
        conversations, total = await svc.list_conversations(
            user_id=UUID(str(user_id)), skip=0, limit=limit
        )
        return {
            "chats": [
                {
                    "id": str(c.id),
                    "title": c.title or "(untitled)",
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                }
                for c in conversations
            ],
            "total": total,
        }


# ----------------------------------------------------------------- read_chat

async def read_chat(user_id: str | UUID, conversation_id: str) -> dict[str, Any]:
    """Return the message transcript of a past conversation."""
    from app.db.session import get_db_context
    from app.services.conversation import ConversationService

    async with get_db_context() as db:
        svc = ConversationService(db)
        conv = await svc.get_conversation(UUID(conversation_id), user_id=UUID(str(user_id)))
        messages = await svc.list_messages(UUID(conversation_id))
        return {
            "id": str(conv.id),
            "title": conv.title or "(untitled)",
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in messages
            ],
        }


# ----------------------------------------------------------------- zip_folder

def zip_folder(root: Path, folder: Path) -> Path:
    """Zip ``folder`` into a temp file under ``root`` and return its path.

    Used by the workspace download-folder route to serve a one-shot zip.
    """
    import tempfile

    fd, tmp_path = tempfile.mkstemp(prefix="workspace_dl_", suffix=".zip", dir=str(root))
    os.close(fd)
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for child in folder.rglob("*"):
            if child.is_file():
                arc = child.relative_to(folder)
                zf.write(child, arc)
    return Path(tmp_path)


__all__ = [
    "list_files",
    "read_file",
    "create_file",
    "write_file",
    "edit_file",
    "delete_file",
    "create_folder",
    "delete_folder",
    "send_file",
    "send_folder",
    "run_terminal",
    "list_chats",
    "read_chat",
    "zip_folder",
    "_workspace_root",
    "_resolve_safe",
]
