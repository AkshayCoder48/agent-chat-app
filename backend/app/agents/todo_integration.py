"""Per-session Todo integration.

Wraps :class:`pydantic_ai_todo.TodoCapability` with a session-scoped
:class:`TodoStorage` + :class:`TodoEventEmitter` so that:

* the agent gets the full todo toolset (``read_todos``, ``write_todos``,
  ``add_todo``, ``update_todo_status`` …) automatically;
* every mutation emits a ``todo_event`` frame to the WebSocket, so the
  frontend ``ResearchPanel`` can render the live plan in real time;
* the client can dismiss / clear the panel via a ``todo_action`` frame
  (the "Cut" button on the UI).

The storage is in-memory and per-session — todos vanish when the WS
disconnects, which matches the chat UX (a new chat starts fresh).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic_ai_todo import (
    TodoCapability,
    TodoEvent,
    TodoEventEmitter,
    TodoEventType,
    TodoStorage,
)
from pydantic_ai_todo.types import Todo

logger = logging.getLogger(__name__)


# Frontend mirror of these statuses lives in `frontend/src/types/chat.ts`
# (`ResearchTodoStatus`). Keep the strings in sync.
TODO_STATUS_ORDER = ("pending", "in_progress", "completed", "blocked")


def todo_to_dict(todo: Todo) -> dict[str, Any]:
    """Serialise a :class:`Todo` to the wire format the frontend expects."""
    return {
        "id": todo.id,
        "content": todo.content,
        "status": todo.status,
        "active_form": todo.active_form,
        "parent_id": todo.parent_id,
        "depends_on": list(todo.depends_on),
    }


class TodoSessionIntegration:
    """Owns the per-WS-session todo storage, emitter, and capability.

    instantiated in :class:`AgentSession.__init__`; the resulting
    :class:`TodoCapability` is handed to ``get_agent()`` so the agent
    transparently gains the todo tools.
    """

    def __init__(
        self,
        emit_callback: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._storage = TodoStorage()
        self._emitter = TodoEventEmitter()
        self._emit = emit_callback
        self._dismissed = False

        # Wire every event type → WS frame. The frontend's
        # `applyTodoEvent(event_type, todo)` switches on the same strings.
        for evt in TodoEventType:
            self._emitter.on(evt, self._make_handler(evt))

    # ------------------------------------------------------------------ API

    @property
    def capability(self) -> TodoCapability:
        """Return a fresh :class:`TodoCapability` bound to our storage."""
        return TodoCapability(
            storage=self._storage,
            enable_subtasks=True,
        )

    @property
    def storage(self) -> TodoStorage:
        return self._storage

    @property
    def dismissed(self) -> bool:
        """True when the user clicked "Cut" — panel should stay hidden
        until the next event arrives (which re-arms it)."""
        return self._dismissed

    def reset(self) -> None:
        """Clear all todos (e.g. on conversation switch)."""
        self._storage.todos = []
        self._dismissed = False

    def set_dismissed(self, value: bool) -> None:
        self._dismissed = value

    def snapshot(self) -> list[dict[str, Any]]:
        """All todos in their current state — sent on (re)connect."""
        return [todo_to_dict(t) for t in self._storage.todos]

    # ------------------------------------------------------------------ impl

    def _make_handler(
        self, evt: TodoEventType
    ) -> Callable[[TodoEvent], Awaitable[None]]:
        async def _handler(event: TodoEvent) -> None:
            # Re-arm the panel on any new event after a dismiss.
            self._dismissed = False
            payload = {
                "event_type": evt.value,
                "todo": todo_to_dict(event.todo),
                "previous": (
                    todo_to_dict(event.previous_state)
                    if event.previous_state is not None
                    else None
                ),
                "ts": event.timestamp.isoformat() if event.timestamp else None,
                "all_todos": self.snapshot(),
            }
            try:
                await self._emit("todo_event", payload)
            except Exception:  # pragma: no cover — emitter must not crash agent
                logger.warning("todo_event emit failed", exc_info=True)

        return _handler


__all__ = ["TodoSessionIntegration", "todo_to_dict", "TODO_STATUS_ORDER"]
