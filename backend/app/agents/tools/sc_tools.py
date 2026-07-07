"""Slash-command tools the AI can call to manage the user's `/shortcuts`.

Three tools are exposed (registered in :mod:`app.agents.assistant`):

  * ``create_sc``  — create a new slash command (name + prompt)
  * ``edit_sc``    — update an existing command's prompt or name
  * ``delete_sc``  — remove a command

"sc" stands for "slash command". These tools let the AI collaboratively
build shortcuts with the user during a chat — e.g. the user says "make a
/research command that searches the web and writes a summary", the AI
calls ``create_sc(name="research", prompt="…")`` and the new command is
immediately available in the slash palette on the next render.

All three tools operate on the current user's slash-command table via the
existing :class:`UserSlashCommandService` — no new persistence layer.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.db.session import get_db_context
from app.schemas.user_slash_command import (
    UserSlashCommandCustomCreate,
    UserSlashCommandUpdate,
)
from app.services.user_slash_command import UserSlashCommandService

logger = logging.getLogger(__name__)

# Same pattern as the schema — lowercase letters, digits, hyphens.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


class CreateSCArgs(BaseModel):
    name: str = Field(
        ...,
        description="The /name of the new slash command (lowercase, digits, hyphens; max 32 chars).",
    )
    prompt: str = Field(
        ...,
        description="The full prompt the command expands to when the user types /<name>.",
    )
    is_enabled: bool = Field(
        default=True,
        description="Whether the command is enabled immediately. Default true.",
    )


class EditSCArgs(BaseModel):
    name: str = Field(
        ...,
        description="The current /name of the command to edit.",
    )
    new_name: str | None = Field(
        default=None,
        description="Optional new name. If omitted, the name is unchanged.",
    )
    new_prompt: str | None = Field(
        default=None,
        description="Optional new prompt body. If omitted, the prompt is unchanged.",
    )
    is_enabled: bool | None = Field(
        default=None,
        description="Optional enable/disable flag. If omitted, the flag is unchanged.",
    )


class DeleteSCArgs(BaseModel):
    name: str = Field(
        ...,
        description="The /name of the command to delete.",
    )


async def _list_commands(user_id: UUID) -> list[dict[str, Any]]:
    """Return the user's commands as a list of plain dicts (for the AI's view)."""
    async with get_db_context() as db:
        svc = UserSlashCommandService(db)
        items, _ = await svc.list_for_user(user_id=user_id)
        return [
            {
                "id": str(c.id),
                "name": c.name,
                "prompt": c.prompt,
                "is_enabled": c.is_enabled,
                "is_custom": c.prompt is not None,
            }
            for c in items
        ]


async def _find_by_name(user_id: UUID, name: str) -> dict[str, Any] | None:
    """Return the user's command with the given name, or None."""
    for c in await _list_commands(user_id):
        if c["name"] == name:
            return c
    return None


async def create_sc(user_id: str | UUID, args: CreateSCArgs) -> dict[str, Any]:
    """Create a new user-defined slash command.

    Returns ``{"ok": true, "name", "id"}`` on success, or
    ``{"ok": false, "error": "..."}`` if a command with that name already
    exists or the name is invalid.
    """
    name = args.name.strip().lower()
    if not _NAME_RE.match(name):
        return {
            "ok": False,
            "error": (
                "Invalid name. Use lowercase letters, digits, and hyphens only; "
                "1–32 chars; must start with a letter or digit."
            ),
        }
    if not args.prompt.strip():
        return {"ok": False, "error": "Prompt must not be empty."}

    try:
        async with get_db_context() as db:
            svc = UserSlashCommandService(db)
            cmd = await svc.create_custom(
                user_id=UUID(str(user_id)),
                data=UserSlashCommandCustomCreate(
                    name=name,
                    prompt=args.prompt.strip(),
                    is_enabled=args.is_enabled,
                ),
            )
            return {
                "ok": True,
                "name": cmd.name,
                "id": str(cmd.id),
                "message": f"Created /{name}. The user can now type /{name} to use it.",
            }
    except AlreadyExistsError:
        return {
            "ok": False,
            "error": f"A slash command named /{name} already exists. Use edit_sc to modify it.",
        }
    except Exception as exc:
        logger.warning("create_sc failed", exc_info=True)
        return {"ok": False, "error": f"Failed to create: {exc}"}


async def edit_sc(user_id: str | UUID, args: EditSCArgs) -> dict[str, Any]:
    """Edit an existing slash command's name, prompt, or enabled flag."""
    name = args.name.strip().lower()
    if not _NAME_RE.match(name):
        return {"ok": False, "error": "Invalid current name."}

    existing = await _find_by_name(UUID(str(user_id)), name)
    if existing is None:
        return {"ok": False, "error": f"No slash command named /{name} found."}
    if not existing["is_custom"]:
        return {
            "ok": False,
            "error": (
                f"/{name} is a built-in command — you can only toggle its enabled "
                "flag, not edit its prompt. Set is_enabled=true/false instead."
            ),
        }

    update_data: dict[str, Any] = {}
    if args.new_name is not None:
        new_name = args.new_name.strip().lower()
        if not _NAME_RE.match(new_name):
            return {"ok": False, "error": "Invalid new_name."}
        if new_name != name:
            update_data["name"] = new_name
    if args.new_prompt is not None:
        if not args.new_prompt.strip():
            return {"ok": False, "error": "new_prompt must not be empty."}
        update_data["prompt"] = args.new_prompt.strip()
    if args.is_enabled is not None:
        update_data["is_enabled"] = args.is_enabled

    if not update_data:
        return {"ok": False, "error": "No edits requested (all fields null)."}

    try:
        async with get_db_context() as db:
            svc = UserSlashCommandService(db)
            cmd = await svc.update(
                user_id=UUID(str(user_id)),
                command_id=UUID(existing["id"]),
                data=UserSlashCommandUpdate(**update_data),
            )
            return {
                "ok": True,
                "name": cmd.name,
                "id": str(cmd.id),
                "message": f"Updated /{name}.",
            }
    except AlreadyExistsError:
        return {
            "ok": False,
            "error": f"A slash command named /{args.new_name} already exists.",
        }
    except NotFoundError:
        return {"ok": False, "error": f"Slash command /{name} disappeared mid-edit."}
    except Exception as exc:
        logger.warning("edit_sc failed", exc_info=True)
        return {"ok": False, "error": f"Failed to edit: {exc}"}


async def delete_sc(user_id: str | UUID, args: DeleteSCArgs) -> dict[str, Any]:
    """Delete a slash command by name."""
    name = args.name.strip().lower()
    if not _NAME_RE.match(name):
        return {"ok": False, "error": "Invalid name."}

    existing = await _find_by_name(UUID(str(user_id)), name)
    if existing is None:
        return {"ok": False, "error": f"No slash command named /{name} found."}

    try:
        async with get_db_context() as db:
            svc = UserSlashCommandService(db)
            await svc.delete(
                user_id=UUID(str(user_id)),
                command_id=UUID(existing["id"]),
            )
            note = (
                f"Deleted /{name}. (It was a built-in override — the built-in is "
                "now back to its default enabled state.)"
                if not existing["is_custom"]
                else f"Deleted /{name}."
            )
            return {"ok": True, "name": name, "message": note}
    except NotFoundError:
        return {"ok": False, "error": f"Slash command /{name} disappeared mid-delete."}
    except Exception as exc:
        logger.warning("delete_sc failed", exc_info=True)
        return {"ok": False, "error": f"Failed to delete: {exc}"}


async def list_sc(user_id: str | UUID) -> dict[str, Any]:
    """List the user's slash commands (helper tool so the AI can see what exists)."""
    items = await _list_commands(UUID(str(user_id)))
    return {"ok": True, "commands": items, "count": len(items)}


__all__ = [
    "CreateSCArgs",
    "EditSCArgs",
    "DeleteSCArgs",
    "create_sc",
    "edit_sc",
    "delete_sc",
    "list_sc",
]
