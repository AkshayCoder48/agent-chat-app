
# Thin session wrapper — the route is lifecycle plumbing only; orchestration lives here.
import asyncio
import contextlib
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from pydantic_ai import (
    Agent,
    FinalResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
    ToolCallPartDelta,
)
from pydantic_ai.messages import (
    BinaryContent,
    TextPart,
    ThinkingPart,
    ThinkingPartDelta,
)

from app.agents.assistant import Deps, get_agent
from app.agents.reasoning_transport import reset_reasoning_callback, set_reasoning_callback
from app.agents.todo_integration import TodoSessionIntegration
from app.services.agent import (
    build_message_history,
    persist_assistant_turn,
    persist_user_turn,
    send_event,
)
from app.db.models.user import User
from app.api.deps import get_conversation_service
from app.db.session import get_db_context
from app.services.file_storage import get_file_storage
from app.repositories import ai_provider_repo

logger = logging.getLogger(__name__)


class AgentSession:
    """One WebSocket session with the AI agent."""

    def __init__(
        self,
        websocket: WebSocket,
        user: User,
    ) -> None:
        self.websocket = websocket
        self.user = user
        self.conversation_history: list[dict[str, str]] = []
        # Inject the user's id + name into Deps so tools (list_chats, etc.)
        # can scope their work to the current user instead of crashing with
        # "no user context".
        self.deps = Deps(
            user_id=str(user.id),
            user_name=getattr(user, "name", None) or getattr(user, "email", None),
        )
        self.deps.ask_user = self._ask_user
        self.current_conversation_id: str | None = None
        self._turn_task: asyncio.Task[None] | None = None
        self._ask_user_future: asyncio.Future[list[dict[str, Any]]] | None = None
        # Per-session todo integration: in-memory TodoStorage + emitter that
        # forwards every mutation to the client as a `todo_event` WS frame.
        # The resulting TodoCapability is passed to get_agent() below so the
        # agent transparently gains read_todos / write_todos / add_todo / …
        self.todo_integration = TodoSessionIntegration(
            emit_callback=lambda evt, payload: send_event(self.websocket, evt, payload)
        )
        # Per-user prompt + skills + tools + MCP servers. Loaded lazily on
        # the first turn (so a fresh WS doesn't pay the DB hit if the user
        # just opens the page and watches).
        self._user_extras_loaded = False
        self._user_system_prompt: str | None = None
        self._user_skills_dir = None
        self._user_custom_tools: list[dict[str, Any]] = []
        self._user_mcp_servers: list[dict[str, Any]] = []

    async def handle_frame(self, data: dict[str, Any]) -> None:
        """Dispatch one incoming WebSocket frame.

        A ``stop`` cancels the running turn; an ``ask_user_response`` unblocks a
        paused run; a ``todo_action`` controls the todo panel (dismiss / reset);
        any other control frame is ignored; a bare message starts a new turn as
        a cancellable background task.
        """
        msg_type = data.get("type")

        if msg_type == "stop":
            await self._cancel_turn()
            return

        if msg_type == "ask_user_response":
            fut = self._ask_user_future
            if fut is not None and not fut.done():
                answers = data.get("answers")
                fut.set_result(answers if isinstance(answers, list) else [])
            return

        if msg_type == "todo_action":
            action = data.get("action")
            if action == "dismiss":
                self.todo_integration.set_dismissed(True)
            elif action == "reset":
                self.todo_integration.reset()
                await send_event(
                    self.websocket,
                    "todo_event",
                    {
                        "event_type": "reset",
                        "todo": None,
                        "previous": None,
                        "ts": None,
                        "all_todos": self.todo_integration.snapshot(),
                    },
                )
            elif action == "snapshot":
                # Client (re)connected mid-session — re-send the current state.
                await send_event(
                    self.websocket,
                    "todo_event",
                    {
                        "event_type": "snapshot",
                        "todo": None,
                        "previous": None,
                        "ts": None,
                        "all_todos": self.todo_integration.snapshot(),
                    },
                )
            return

        if msg_type is not None:
            return

        if self._turn_task is not None and not self._turn_task.done():
            logger.warning("Ignoring message received while a turn is already in progress")
            return
        task = asyncio.create_task(self._run_turn(data))
        self._turn_task = task
        task.add_done_callback(self._on_turn_done)

    def _on_turn_done(self, task: asyncio.Task[None]) -> None:
        """Clear the turn slot and surface unexpected crashes."""
        if self._turn_task is task:
            self._turn_task = None
        if not task.cancelled():
            exc = task.exception()
            if isinstance(exc, WebSocketDisconnect):
                logger.info("Client disconnected during agent turn")
            elif exc is not None:
                logger.error("Agent turn task crashed", exc_info=exc)

    async def _run_turn(self, data: dict[str, Any]) -> None:
        """Run one turn, emitting a terminal ``complete`` even when stopped."""
        try:
            await self.process_message(data)
        except asyncio.CancelledError:
            await send_event(
                self.websocket,
                "complete",
                {
                    "conversation_id": self.current_conversation_id,
                    "stopped": True,
                },
            )
            raise

    async def _cancel_turn(self) -> None:
        """Cancel the in-flight turn task and wait for it to unwind."""
        task = self._turn_task
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def shutdown(self) -> None:
        """Cancel any in-flight turn and tear down the Hopx sandbox."""
        await self._cancel_turn()
        # Tear down the user's Hopx sandbox if one was created during the
        # session. Best-effort — failures don't crash shutdown.
        try:
            from app.agents.tools.workspace_tools import destroy_hopx_session
            await destroy_hopx_session(self.user.id)
        except Exception:
            logger.debug("Hopx teardown failed (non-fatal)", exc_info=True)

    async def process_message(self, data: dict[str, Any]) -> None:
        """Process one user turn: persist input, run the agent, stream events, persist output."""
        user_message = data.get("message", "")
        file_ids = data.get("file_ids", [])

        if not user_message and not file_ids:
            await send_event(self.websocket, "error", {"message": "Empty message"})
            return

        # Detect conversation switch and reset the per-session todo list so the
        # new chat starts with a clean plan panel rather than inheriting the
        # previous thread's tasks.
        requested_conv_id = data.get("conversation_id")
        prior_conv_id = self.current_conversation_id
        if (
            requested_conv_id
            and prior_conv_id
            and str(requested_conv_id) != str(prior_conv_id)
        ):
            self.todo_integration.reset()
            await send_event(
                self.websocket,
                "todo_event",
                {
                    "event_type": "reset",
                    "todo": None,
                    "previous": None,
                    "ts": None,
                    "all_todos": [],
                },
            )

        self.current_conversation_id, newly_created, organization_id = await persist_user_turn(
            self.user,
            user_message,
            file_ids,
            requested_conversation_id=data.get("conversation_id"),
            current_conversation_id=self.current_conversation_id,
        )
        if newly_created and self.current_conversation_id:
            await send_event(
                self.websocket,
                "conversation_created",
                {"conversation_id": self.current_conversation_id},
            )

        await send_event(self.websocket, "user_prompt", {"content": user_message})

        try:
            # Lazy-load per-user prompt + skills + tools + MCP servers on the
            # first turn. Cached for the rest of the WS session.
            if not self._user_extras_loaded:
                await self._load_user_extras()
                self._user_extras_loaded = True

            # If the client picked a model from one of their custom providers
            # (frame carries provider_id), look up that provider, decrypt the
            # API key, and route the chat request to the provider's base_url.
            provider_base_url: str | None = None
            provider_api_key: str | None = None
            provider_id = data.get("provider_id")
            selected_model = data.get("model")
            if provider_id:
                try:
                    async with get_db_context() as prov_db:
                        prov = await ai_provider_repo.get_by_id(prov_db, provider_id)
                        if prov is not None and prov.user_id == self.user.id:
                            provider_base_url = prov.base_url
                            provider_api_key = (
                                ai_provider_repo.get_decrypted_api_key(prov)
                                if prov.api_key_encrypted
                                else None
                            )
                            if not selected_model and prov.models:
                                selected_model = prov.models[0]
                except Exception:
                    logger.warning(
                        "Failed to look up provider %s — falling back to default",
                        provider_id,
                        exc_info=True,
                    )

            assistant = get_agent(
                model_name=selected_model,
                thinking_effort=data.get("thinking_effort"),
                todo_capability=self.todo_integration.capability,
                provider_base_url=provider_base_url,
                provider_api_key=provider_api_key,
                system_prompt=self._user_system_prompt,
                user_skills_dir=self._user_skills_dir,
                custom_tools=self._user_custom_tools,
                mcp_servers=self._user_mcp_servers,
            )
            model_history = build_message_history(self.conversation_history)
            user_input = await self._build_multimodal_input(user_message, file_ids)

            # Bind a per-turn reasoning callback so ReasoningAwareTransport
            # (only active for custom-provider turns) can stream
            # ``reasoning_content`` deltas straight to the client as
            # ``reasoning_delta`` WS events. The previous thinking/text
            # parsers are untouched — both run side-by-side.
            async def _emit_reasoning_delta(content: str) -> None:
                await send_event(
                    self.websocket,
                    "reasoning_delta",
                    {"index": 0, "content": content},
                )

            reasoning_token = set_reasoning_callback(_emit_reasoning_delta)
            try:
                collected_tool_calls: list[dict[str, Any]] = []
                async with assistant.agent.iter(
                    user_input, deps=self.deps, message_history=model_history
                ) as agent_run:
                    await self._stream_agent_run(agent_run, user_message, collected_tool_calls)
            finally:
                reset_reasoning_callback(reasoning_token)

            # Update in-memory history only after a complete agent run
            if agent_run.result is not None:
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append(
                    {"role": "assistant", "content": agent_run.result.output}
                )
            assistant_msg_id: str | None = None
            if self.current_conversation_id and agent_run.result is not None:
                assistant_msg_id = await persist_assistant_turn(
                    self.current_conversation_id,
                    agent_run.result.output,
                    getattr(assistant, "model_name", None),
                    collected_tool_calls,
                )

            if assistant_msg_id:
                await send_event(
                    self.websocket,
                    "message_saved",
                    {
                        "message_id": assistant_msg_id,
                        "conversation_id": self.current_conversation_id,
                    },
                )

            await send_event(
                self.websocket,
                "complete",
                {"conversation_id": self.current_conversation_id},
            )
        except WebSocketDisconnect:
            raise
        except Exception as e:
            logger.exception("Error processing agent request")
            await send_event(self.websocket, "error", {"message": str(e)})

    async def _ask_user(self, questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Pause the run: ask the client questions and block until they answer.

        Emits an ``ask_user`` event with the whole batch, then awaits a future the
        frame dispatcher completes when the matching ``ask_user_response`` arrives.
        The client returns a list of answers parallel to the questions.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[list[dict[str, Any]]] = loop.create_future()
        self._ask_user_future = fut
        try:
            await send_event(self.websocket, "ask_user", {"questions": questions})
            return await fut
        finally:
            self._ask_user_future = None

    async def _load_user_extras(self) -> None:
        """Load per-user system prompt + skills dir + custom tools + MCP servers.

        Cached in ``self._user_*`` after the first call. Failures are logged
        and silently degrade — the agent keeps working with the default prompt
        and no skills/tools/MCPs.
        """
        from pathlib import Path

        from app.agents.prompts import build_user_system_prompt, load_user_prompt_extras
        from app.core.config import settings

        try:
            extras = await load_user_prompt_extras(self.user.id)
            self._user_skills_dir = Path(settings.MEDIA_DIR) / "skills" / str(self.user.id)
            self._user_custom_tools = extras.get("custom_tools") or []
            self._user_mcp_servers = extras.get("mcp_servers") or []
            self._user_system_prompt = build_user_system_prompt(
                user_id=self.user.id,
                skills=extras.get("skills"),
                mcp_servers=extras.get("mcp_servers"),
                custom_tools=extras.get("custom_tools"),
                env_vars=extras.get("env_vars"),
                user_override=extras.get("user_override"),
                user_override_enabled=bool(extras.get("user_override_enabled")),
            )
        except Exception:
            logger.warning("Failed to load user prompt extras", exc_info=True)


    async def _build_multimodal_input(
        self, user_message: str, file_ids: list[Any]
    ) -> str | list[Any]:
        """Fold attached images and parsed file text into the user message."""
        if not file_ids:
            return user_message

        storage = get_file_storage()
        image_parts: list[BinaryContent] = []
        file_context_parts: list[str] = []
        async with get_db_context() as file_db:
            attached_files = await get_conversation_service(file_db).list_attached_files(file_ids)
            for chat_file in attached_files:
                try:
                    if chat_file.file_type == "image":
                        file_data = await storage.load(chat_file.storage_path)
                        image_parts.append(
                            BinaryContent(data=file_data, media_type=chat_file.mime_type)
                        )
                    elif chat_file.parsed_content:
                        file_context_parts.append(
                            f"\n---\nAttached file: {chat_file.filename}\n```\n{chat_file.parsed_content}\n```"
                        )
                except Exception:
                    logger.warning("Failed to load file %s", chat_file.id, exc_info=True)

        full_text = user_message + "".join(file_context_parts)
        if image_parts:
            return [full_text, *image_parts]
        return full_text

    async def _stream_agent_run(
        self,
        agent_run: Any,
        user_message: str,
        collected_tool_calls: list[dict[str, Any]],
    ) -> None:
        """Drive the agent_run iterator, dispatching each node to its streaming helper."""
        async for node in agent_run:
            if Agent.is_user_prompt_node(node):
                prompt_text = (
                    node.user_prompt if isinstance(node.user_prompt, str) else user_message
                )
                await send_event(
                    self.websocket, "user_prompt_processed", {"prompt": prompt_text}
                )
            elif Agent.is_model_request_node(node):
                await send_event(self.websocket, "model_request_start", {})
                async with node.stream(agent_run.ctx) as request_stream:
                    await self._stream_request_events(request_stream)
            elif Agent.is_call_tools_node(node):
                await send_event(self.websocket, "call_tools_start", {})
                async with node.stream(agent_run.ctx) as handle_stream:
                    await self._stream_tool_events(handle_stream, collected_tool_calls)
            elif Agent.is_end_node(node) and agent_run.result is not None:
                await send_event(
                    self.websocket, "final_result", {"output": agent_run.result.output}
                )

    async def _stream_request_events(self, request_stream: Any) -> None:
        """Forward model-request events (text/thinking/tool deltas + final-result start).
        """
        async for event in request_stream:
            if isinstance(event, PartStartEvent):
                await send_event(
                    self.websocket,
                    "part_start",
                    {"index": event.index, "part_type": type(event.part).__name__},
                )
                if isinstance(event.part, TextPart) and event.part.content:
                    await send_event(
                        self.websocket,
                        "text_delta",
                        {"index": event.index, "content": event.part.content},
                    )
                elif isinstance(event.part, ThinkingPart) and event.part.content:
                    await send_event(
                        self.websocket,
                        "thinking_delta",
                        {"index": event.index, "content": event.part.content},
                    )
            elif isinstance(event, PartDeltaEvent):
                if isinstance(event.delta, TextPartDelta):
                    await send_event(
                        self.websocket,
                        "text_delta",
                        {"index": event.index, "content": event.delta.content_delta},
                    )
                elif isinstance(event.delta, ThinkingPartDelta):
                    if event.delta.content_delta:
                        await send_event(
                            self.websocket,
                            "thinking_delta",
                            {"index": event.index, "content": event.delta.content_delta},
                        )
                elif isinstance(event.delta, ToolCallPartDelta):
                    await send_event(
                        self.websocket,
                        "tool_call_delta",
                        {"index": event.index, "args_delta": event.delta.args_delta},
                    )
            elif isinstance(event, FinalResultEvent):
                await send_event(
                    self.websocket,
                    "final_result_start",
                    {"tool_name": event.tool_name},
                )

    async def _stream_tool_events(
        self,
        handle_stream: Any,
        collected_tool_calls: list[dict[str, Any]],
    ) -> None:
        """Forward tool-call/result events; collect tool calls (with results) for persistence."""
        pending: dict[str, dict[str, Any]] = {}
        async for tool_event in handle_stream:
            if isinstance(tool_event, FunctionToolCallEvent):
                tc = {
                    "tool_call_id": tool_event.part.tool_call_id,
                    "tool_name": tool_event.part.tool_name,
                    "args": tool_event.part.args_as_dict(raise_if_invalid=False),
                }
                collected_tool_calls.append(tc)
                pending[tool_event.part.tool_call_id] = tc
                await send_event(self.websocket, "tool_call", tc)
            elif isinstance(tool_event, FunctionToolResultEvent):
                # pydantic-ai 1.x: the result payload is on `tool_event.part`
                # (a ToolReturnPart | RetryPromptPart), NOT `tool_event.result`.
                # `tool_call_id` is a property on the base ToolResultEvent.
                result_part = tool_event.part
                result_text = (
                    result_part.content if hasattr(result_part, "content") else str(result_part)
                )
                tc = pending.get(tool_event.tool_call_id)
                if tc is not None:
                    tc["result"] = str(result_text)
                await send_event(
                    self.websocket,
                    "tool_result",
                    {
                        "tool_call_id": tool_event.tool_call_id,
                        "content": str(result_text),
                    },
                )
