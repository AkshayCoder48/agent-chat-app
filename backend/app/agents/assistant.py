
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.capabilities import (
    ReinjectSystemPrompt,
    Thinking,
    WebFetch,
    WebSearch,
)
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from app.agents.prompts import DEFAULT_SYSTEM_PROMPT
from app.agents.prompts import get_system_prompt_with_rag
from app.agents.prompts import build_user_system_prompt
from app.agents.reasoning_transport import build_reasoning_aware_client
from pydantic_ai_todo import TodoCapability
from app.agents.tools.ask_user_tool import MAX_QUESTIONS, QuestionItem, format_answers, parse_questions
from app.agents.utils import get_current_datetime
from app.agents.tools.rag_tool import search_knowledge_base
from app.agents.tools.chart_tool import ChartType, create_chart
from app.agents.tools.code_execution import run_python as run_python_code
from app.agents.tools.workspace_tools import (
    create_file as ws_create_file,
    create_folder as ws_create_folder,
    delete_file as ws_delete_file,
    delete_folder as ws_delete_folder,
    edit_file as ws_edit_file,
    list_chats as ws_list_chats,
    list_files as ws_list_files,
    read_chat as ws_read_chat,
    read_file as ws_read_file,
    run_terminal as ws_run_terminal,
    send_file as ws_send_file,
    send_folder as ws_send_folder,
    write_file as ws_write_file,
)
from app.agents.tools.sc_tools import (
    CreateSCArgs as SCCreateArgs,
    DeleteSCArgs as SCDeleteArgs,
    EditSCArgs as SCEditArgs,
    create_sc as sc_create,
    delete_sc as sc_delete,
    edit_sc as sc_edit,
    list_sc as sc_list,
)
from app.agents.tools.env_tools import (
    DeleteEnvArgs,
    SetEnvArgs,
    delete_env as env_delete,
    list_env as env_list,
    set_env as env_set,
)
from pathlib import Path

from pydantic_ai_skills import SkillsToolset
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    """User-configured OpenAI-compatible provider endpoint.

    ``model_type`` selects which OpenAI API surface to call:
      * ``"chat"``     -> POST /v1/chat/completions  (universal — works with
        every OpenAI-compatible provider including g4f.space, OpenRouter,
        Groq, Together, Ollama, vLLM, LM Studio, …). This is the default
        because most third-party providers do NOT implement the newer
        Responses API and would silently hang the SSE parser waiting for
        a chunk that never arrives.
      * ``"responses"`` -> POST /v1/responses        (OpenAI direct only).

    ``tools_enabled`` controls whether the agent registers its tool suite
    (workspace ops, code execution, RAG search, charts, ask_user, …) on
    the model at all. Some providers (notably certain g4f / free models)
    reject any request that includes a ``tools`` array via HTTP 403 —
    toggling this off lets the user still chat in text-only mode.
    """

    base_url: str
    api_key: str | None
    model_name: str
    model_type: Literal["chat", "responses"] = "chat"
    tools_enabled: bool = True


def _build_model_from_provider_config(cfg: ProviderConfig) -> Any:
    """Build the right pydantic-ai model for a provider configuration.

    Routes to :class:`OpenAIChatModel` (POST /v1/chat/completions) when
    ``model_type == "chat"`` and :class:`OpenAIResponsesModel` (POST
    /v1/responses) when ``model_type == "responses"``.

    The Chat Completions path is wrapped with :func:`build_reasoning_aware_client`
    so non-standard ``delta.reasoning_content`` fields (DeepSeek / Moonshot /
    g4f) are extracted into a contextvar callback the frontend can render in
    a separate "Reasoning" block.
    """
    resolved_key = cfg.api_key or "unset"

    # Chat Completions — universal endpoint. Wrap with ReasoningAwareTransport
    # which: (1) filters out empty-choices chunks (the usage-only chunk that
    # crashes pydantic-ai's parser on some non-standard providers like
    # g4f.space), and (2) extracts the non-standard ``delta.reasoning_content``
    # field (DeepSeek / Moonshot / g4f) and emits it via a contextvar callback
    # so the frontend can render it in a separate "Reasoning" block — distinct
    # from OpenAI-native reasoning summaries that come through the ``Thinking``
    # capability.
    http_client = build_reasoning_aware_client(
        base_url=cfg.base_url,
        api_key=resolved_key,
    )
    provider = OpenAIProvider(
        api_key=resolved_key,
        base_url=cfg.base_url,
        http_client=http_client,
    )
    if cfg.model_type == "responses":
        return OpenAIResponsesModel(cfg.model_name, provider=provider)
    return OpenAIChatModel(cfg.model_name, provider=provider)


def _build_model(
    model_name: str,
    base_url: str | None = None,
    api_key: str | None = None,
    model_type: Literal["chat", "responses"] = "chat",
) -> Any:
    """Build an OpenAI-compatible model client.

    If ``base_url`` + ``api_key`` are provided, route to the user's custom
    provider (OpenRouter, Groq, Together, Ollama, vLLM, LM Studio, g4f, …)
    via :class:`OpenAIChatModel` by default — most third-party OpenAI-compatible
    providers only support ``/v1/chat/completions``, not the newer Responses
    API. The ``model_type`` argument lets the user opt into the Responses API
    for OpenAI-direct (which is the only provider that implements it).

    For the default (no base_url), use :class:`OpenAIResponsesModel` against
    the real OpenAI API so we get reasoning summaries, native tools, etc.
    """
    resolved_model = model_name or settings.AI_MODEL
    resolved_key = api_key or settings.OPENAI_API_KEY

    if base_url:
        return _build_model_from_provider_config(
            ProviderConfig(
                base_url=base_url,
                api_key=api_key,
                model_name=resolved_model,
                model_type=model_type,
            )
        )

    # Default OpenAI — use the Responses API.
    provider_kwargs: dict[str, Any] = {"api_key": resolved_key}
    return OpenAIResponsesModel(
        resolved_model,
        provider=OpenAIProvider(**provider_kwargs),
    )


AskUserCallback = Callable[[list[dict[str, Any]]], Awaitable[list[dict[str, Any]]]]


@dataclass
class Deps:
    """Dependencies passed to tools via RunContext."""

    user_id: str | None = None
    user_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    ask_user: AskUserCallback | None = None


class AssistantAgent:
    def __init__(
        self,
        model_name: str | None = None,
        temperature: float | None = None,
        system_prompt: str | None = None,
        thinking_effort: str | None = None,
        todo_capability: "TodoCapability | None" = None,
        provider_base_url: str | None = None,
        provider_api_key: str | None = None,
        provider_model_type: Literal["chat", "responses"] = "chat",
        provider_tools_enabled: bool = True,
        user_skills_dir: Path | None = None,
        custom_tools: list[dict[str, Any]] | None = None,
        mcp_servers: list[dict[str, Any]] | None = None,
    ):
        self.todo_capability = todo_capability
        self.model_name = model_name or settings.AI_MODEL
        self.provider_base_url = provider_base_url
        self.provider_api_key = provider_api_key
        # ``provider_model_type`` controls whether we hit
        # POST /v1/chat/completions ("chat" — default, universal) or
        # POST /v1/responses ("responses" — OpenAI-direct only). Most
        # third-party providers (g4f.space, OpenRouter, Groq, …) only
        # implement the chat-completions endpoint; routing them through
        # OpenAIResponsesModel is the root cause of stuck-at-thinking.
        self.provider_model_type = provider_model_type
        # ``provider_tools_enabled`` lets the user disable tool registration
        # entirely for providers that 403 on the ``tools`` array. Text-only
        # chat still works — only tool calls are skipped.
        self.provider_tools_enabled = provider_tools_enabled
        # ``temperature`` stays ``None`` when caller didn't set it — don't fall
        # back to settings.AI_TEMPERATURE here. Reasoning/o-series models
        # (gpt-5.5, o1, …) reject the parameter entirely, so we only forward
        # it to the model when explicitly requested.
        self.temperature = temperature
        self.thinking_effort = (
            thinking_effort
            if thinking_effort is not None
            else (settings.AI_THINKING_EFFORT if settings.AI_THINKING_ENABLED else None)
        )
        # The caller may pass a fully-built prompt (with skill/MCP/tool
        # sections already appended via build_user_system_prompt); otherwise
        # we fall back to the static default.
        self.system_prompt = system_prompt or get_system_prompt_with_rag()
        self.user_skills_dir = user_skills_dir
        self.custom_tools = custom_tools or []
        self.mcp_servers = mcp_servers or []
        self._agent: Agent[Deps, str] | None = None

    def _create_agent(self) -> Agent[Deps, str]:
        model = _build_model(
            self.model_name,
            base_url=self.provider_base_url,
            api_key=self.provider_api_key,
            model_type=self.provider_model_type,
        )

        capabilities: list[Any] = [ReinjectSystemPrompt()]
        if self.thinking_effort:
            capabilities.append(Thinking(effort=self.thinking_effort))  # ty: ignore[invalid-argument-type]
        # Local DuckDuckGo / fetch (the installed extras) — works uniformly across
        # all providers, unlike provider-native web search.
        capabilities.append(WebSearch(native=False, local="duckduckgo"))
        capabilities.append(WebFetch(native=False, local=True))

        # The unified ``Thinking()`` capability enables reasoning, but for the
        # OpenAI Responses API it sets only the effort — not the *summary*
        # field that controls whether the model streams reasoning summaries
        # back to the client. Without ``openai_reasoning_summary`` set, the
        # model reasons internally and we never see ThinkingPart events.
        # ``openai_*``-prefixed fields on TypedDict settings are silently
        # ignored by other providers, so this is safe to apply unconditionally.
        model_settings: ModelSettings = ModelSettings()
        if self.temperature is not None:
            model_settings["temperature"] = self.temperature
        if self.thinking_effort:
            model_settings["openai_reasoning_summary"] = "auto"  # type: ignore[typeddict-unknown-key]  # ty: ignore[invalid-key]
        toolsets: list[Any] = []

        # Per-user skills directory (uploaded / installed via Settings →
        # Skills). Falls back to the legacy shared dir when not set.
        skills_dirs: list[str] = []
        if self.user_skills_dir is not None and self.user_skills_dir.exists():
            skills_dirs.append(str(self.user_skills_dir))
        legacy_skills_dir = Path(__file__).parent.parent.parent / "skills"
        if legacy_skills_dir.exists():
            skills_dirs.append(str(legacy_skills_dir))
        # When the user has explicitly disabled tools for this provider
        # (provider_tools_enabled=False), skip SkillsToolset too — Skills
        # register as a toolset and would re-introduce the ``tools`` array
        # that the provider 403s on.
        if self.provider_tools_enabled and skills_dirs:
            try:
                toolsets.append(SkillsToolset(directories=skills_dirs))
            except Exception:
                logger.warning("Failed to load SkillsToolset", exc_info=True)

        # MCP servers — spin up a pydantic-ai toolset per active server.
        # Failures are logged but don't break the chat (the agent just
        # doesn't see that server's tools). Skipped entirely when
        # provider_tools_enabled=False to keep the request body free of
        # any ``tools`` array.
        if self.provider_tools_enabled:
            for srv in self.mcp_servers:
                try:
                    ts = _build_mcp_toolset(srv)
                    if ts is not None:
                        toolsets.append(ts)
                except Exception:
                    logger.warning(
                        "Failed to wire MCP server %s", srv.get("name"), exc_info=True
                    )

        if self.todo_capability is not None:
            capabilities.append(self.todo_capability)

        agent = Agent[Deps, str](
            model=model,
            model_settings=model_settings,
            system_prompt=self.system_prompt,
            capabilities=capabilities,
            toolsets=toolsets,
        )

        # Tools (workspace ops, RAG, charts, ask_user, code execution, …)
        # are only registered when provider_tools_enabled is True. Some
        # providers (notably certain g4f / free models) reject any request
        # that includes a ``tools`` array via HTTP 403 — skipping tool
        # registration keeps the request body clean so chat still works
        # (text-only mode).
        if self.provider_tools_enabled:
            self._register_tools(agent)
            self._register_custom_tools(agent)

        return agent

    def _register_tools(self, agent: Agent[Deps, str]) -> None:
        @agent.tool_plain
        def current_datetime() -> dict[str, str]:
            """Get the current date and time.

            Use this tool when you need to know the current date or time.
            """
            return get_current_datetime()
        @agent.tool
        async def search_documents(
            ctx: RunContext[Deps], query: str, top_k: int = 5
        ) -> str:
            """Search the knowledge base for relevant documents.

            Use this tool to find information from uploaded documents before answering user queries.
            Cite sources by referring to the document filename from the search results.

            Args:
                query: The search query string.
                top_k: Number of top results to retrieve (default: 5).

            Returns:
                Formatted string with search results including content and scores.
            """
            try:
                return await search_knowledge_base(query=query, top_k=top_k)
            except Exception as e:
                raise ModelRetry("Knowledge base temporarily unavailable, please try again.") from e
        @agent.tool_plain
        def create_chart_tool(
            chart_type: ChartType,
            title: str,
            data: list[dict[str, Any]],
            series: list[dict[str, Any]] | None = None,
            x_key: str = "x",
            style: dict[str, Any] | None = None,
        ) -> str:
            """Create a chart (line/bar/pie/area/scatter) to visualize data for the user.

            Use whenever the user asks to plot, chart, graph, or visualize numbers,
            trends, comparisons, or distributions. Do not repeat the returned JSON
            back to the user — just briefly describe the chart you created.

            Args:
                chart_type: One of "line", "bar", "pie", "area", "scatter".
                title: Short chart title.
                data: Row dicts, e.g. [{"x": "Jan", "revenue": 120}]. For pie:
                    [{"x": "Chrome", "value": 64}, ...].
                series: Optional [{"key", "label"?, "color"?}] selecting fields to plot.
                x_key: Row field for the x-axis / pie label (default "x").
                style: Optional {"palette", "grid", "legend", "x_label", "y_label", "stacked"}.
            """
            return create_chart(
                chart_type=chart_type,
                title=title,
                data=data,
                series=series,
                x_key=x_key,
                style=style,
            )

        @agent.tool
        async def ask_user(ctx: RunContext[Deps], questions: Any) -> str:
            """Ask the user one or more questions and wait for their answers.

            Use this when a decision or missing detail would materially change what
            you do next and you can't reasonably assume it. You may pass several
            questions at once — the user answers them one after another and you get
            all the answers back together (good for an intake/setup flow). You can
            also call this again later to follow up on what they said. Prefer
            answering directly when the request is already clear.

            Args:
                questions: The questions to ask. Each has the question text, optional
                    suggested `options`, and `allow_custom` (whether a free-form
                    answer is allowed, default True).

            Returns:
                The user's answers as a Q/A transcript, with skipped questions marked.
            """
            if ctx.deps.ask_user is None:
                return (
                    "User interaction is unavailable here; proceed with a reasonable "
                    "assumption and state it briefly."
                )
            # Coerce + validate. Many OpenAI-compatible providers (notably
            # g4f and other free relays) serialize the ``questions`` array
            # as a JSON string instead of a real JSON array, which fails
            # Pydantic's list validation with "Input should be a valid array".
            # ``parse_questions`` accepts both shapes (string OR list) and
            # drops invalid items instead of crashing the whole turn.
            #
            # The ``Any`` type hint above is deliberate — it lets pydantic-ai
            # forward whatever the model sent (string, list, dict) without
            # rejecting it at the schema-validation layer, then we normalize
            # here. Using ``list[QuestionItem]`` would 409 the request the
            # moment a provider sends a JSON string.
            items = parse_questions(questions)
            if not items:
                return "No questions were provided."
            payload = [q.model_dump() for q in items[:MAX_QUESTIONS]]
            answers = await ctx.deps.ask_user(payload)
            return format_answers(payload, answers)

        @agent.tool
        async def run_python(ctx: RunContext[Deps], code: str) -> str:
            """Run Python in a sandbox and return its output.

            Use for multi-step number-crunching (projections, aggregations, simulations).
            SANDBOX LIMITATIONS — violating these causes "Execution failed" errors:
              - NO comma thousands separator in f-strings: ``{x:,}`` or ``{x:,.2f}``
                CRASHES. Use ``f"${int(x)}"`` or ``f"{x:.2f}"`` instead.
              - NO ``statistics``, ``random``, ``itertools``, ``collections``,
                numpy, pandas — compute stats manually with loops/math.
              - NO file I/O, network calls, or OS access.
              - NO ``import`` of any module not in: math, asyncio, json, datetime, re.
              - Walrus operator ``:=`` is unsupported.
              - f-string expressions must be simple: no ``!r``, no ``=`` suffix
                (``{x=}`` debug format crashes). Use ``print(f"x = {x}")``.

            Args:
                code: The Python source to execute.

            Returns:
                The captured stdout plus the final expression value, or an error
                message you can read and fix.
            """
            return await run_python_code(code)

        # ----------------------------------------------------- workspace tools
        # Per-user file system + terminal. All paths are relative to the
        # user's workspace root; the agent never sees absolute paths.

        @agent.tool
        async def list_files(ctx: RunContext[Deps], path: str = ".") -> str:
            """List files and folders under ``path`` in the user's workspace.

            Args:
                path: Relative path (default: workspace root). Use "." for root.

            Returns:
                A formatted listing: one entry per line with type/size markers.
            """
            result = await ws_list_files(ctx.deps.user_id or "", path)
            if "error" in result:
                return result["error"]
            lines = [f"{path}"]
            for e in result.get("entries", []):
                kind = "DIR " if e["type"] == "folder" else "FILE"
                size = f" ({e.get('size')}B)" if e.get("size") is not None else ""
                lines.append(f"  {kind} {e['name']}{size}")
            return "\n".join(lines) if len(lines) > 1 else f"{path} is empty"

        @agent.tool
        async def read_file(ctx: RunContext[Deps], path: str) -> str:
            """Read the text content of a file in the user's workspace.

            Args:
                path: Relative path inside the workspace.

            Returns:
                The file's text content (capped at 256 KB), or an error message.
            """
            return await ws_read_file(ctx.deps.user_id or "", path)

        @agent.tool
        async def create_file(
            ctx: RunContext[Deps], path: str, content: str, overwrite: bool = False
        ) -> str:
            """Create a new file in the user's workspace.

            Args:
                path: Relative path. Parent folders are created automatically.
                content: Text content to write (max 5 MB).
                overwrite: If False (default), refuse to clobber an existing file.

            Returns:
                A one-line success message.
            """
            return await ws_create_file(
                ctx.deps.user_id or "", path, content, overwrite=overwrite
            )

        @agent.tool
        async def write_file(ctx: RunContext[Deps], path: str, content: str) -> str:
            """Overwrite a file in the user's workspace (creates if missing).

            Args:
                path: Relative path inside the workspace.
                content: New text content.
            """
            return await ws_write_file(ctx.deps.user_id or "", path, content)

        @agent.tool
        async def edit_file(
            ctx: RunContext[Deps],
            path: str,
            find: str,
            replace: str,
            replace_all: bool = True,
        ) -> str:
            """Find-and-replace literal text inside a file in the workspace.

            Args:
                path: Relative path inside the workspace.
                find: Literal substring to find (NOT a regex).
                replace: Replacement substring.
                replace_all: If True (default), replace every occurrence; if
                    False, only the first.
            """
            return await ws_edit_file(
                ctx.deps.user_id or "", path, find, replace, replace_all=replace_all
            )

        @agent.tool
        async def delete_file(ctx: RunContext[Deps], path: str) -> str:
            """Delete a single file from the user's workspace."""
            return await ws_delete_file(ctx.deps.user_id or "", path)

        @agent.tool
        async def create_folder(ctx: RunContext[Deps], path: str) -> str:
            """Create a directory in the user's workspace (mkdir -p semantics)."""
            return await ws_create_folder(ctx.deps.user_id or "", path)

        @agent.tool
        async def delete_folder(ctx: RunContext[Deps], path: str) -> str:
            """Delete a directory tree from the user's workspace (rm -rf)."""
            return await ws_delete_folder(ctx.deps.user_id or "", path)

        @agent.tool
        async def send_file(ctx: RunContext[Deps], path: str) -> str:
            """Return a download descriptor for a file in the workspace.

            Use this when the user asks for a file you've created so they can
            download it. The frontend renders a download card automatically.
            """
            import json as _json
            result = await ws_send_file(ctx.deps.user_id or "", path)
            return _json.dumps(result)

        @agent.tool
        async def send_folder(ctx: RunContext[Deps], path: str) -> str:
            """Return a download descriptor for a folder (served as a zip)."""
            import json as _json
            result = await ws_send_folder(ctx.deps.user_id or "", path)
            return _json.dumps(result)

        @agent.tool
        async def run_terminal(
            ctx: RunContext[Deps], command: str, cwd: str = "."
        ) -> str:
            """Run a shell command inside the user's workspace.

            Only a safe allowlist of binaries may be invoked (ls, cat, grep,
            python3, git, npm, pip, curl, …); shell operators (``|``, ``;``,
            ``&&``, ``>``, ``<``) are NOT supported. The command runs with
            the workspace as cwd.

            Args:
                command: The command line (e.g. ``"ls -la"`` or ``"grep -r foo ."``).
                cwd: Working directory inside the workspace (default: root).

            Returns:
                ``stdout`` / ``stderr`` / ``exit_code`` of the process, or an
                error message.
            """
            import json as _json
            result = await ws_run_terminal(ctx.deps.user_id or "", command, cwd=cwd)
            return _json.dumps(result)

        @agent.tool
        async def list_chats(ctx: RunContext[Deps], limit: int = 20) -> str:
            """List the user's recent chat conversations (titles + IDs).

            Use this when the user asks about a previous chat and you need the ID
            before calling ``read_chat``.

            Args:
                limit: Max number of conversations to return (default 20).
            """
            import json as _json
            result = await ws_list_chats(ctx.deps.user_id or "", limit=limit)
            return _json.dumps(result)

        @agent.tool
        async def read_chat(ctx: RunContext[Deps], conversation_id: str) -> str:
            """Read the full message transcript of a previous chat.

            Args:
                conversation_id: The conversation's UUID (from ``list_chats``).
            """
            import json as _json
            result = await ws_read_chat(ctx.deps.user_id or "", conversation_id)
            return _json.dumps(result)

        # ----------------------------------------------------- slash command tools
        # "sc" = "slash command". Let the AI collaboratively build /shortcuts
        # with the user — e.g. "make a /research command that …". The new
        # command appears in the user's slash palette on the next render.

        @agent.tool
        async def create_sc(ctx: RunContext[Deps], args: SCCreateArgs) -> str:
            """Create a new slash command (shortcut) for the user.

            "sc" stands for "slash command". Use this when the user asks you
            to make a new /<name> shortcut that expands to a stored prompt.
            The new command appears in the user's slash palette immediately.

            Args:
                args: {name, prompt, is_enabled?} — name is lowercase-with-hyphens,
                    prompt is the full text the command expands to.
            """
            import json as _json
            result = await sc_create(ctx.deps.user_id or "", args)
            return _json.dumps(result)

        @agent.tool
        async def edit_sc(ctx: RunContext[Deps], args: SCEditArgs) -> str:
            """Edit an existing slash command's name, prompt, or enabled flag.

            Args:
                args: {name, new_name?, new_prompt?, is_enabled?} — at least one
                    optional field must be set. Only custom commands can be edited;
                    built-in overrides accept is_enabled only.
            """
            import json as _json
            result = await sc_edit(ctx.deps.user_id or "", args)
            return _json.dumps(result)

        @agent.tool
        async def delete_sc(ctx: RunContext[Deps], args: SCDeleteArgs) -> str:
            """Delete a slash command by name.

            Args:
                args: {name} — the /<name> of the command to delete.
            """
            import json as _json
            result = await sc_delete(ctx.deps.user_id or "", args)
            return _json.dumps(result)

        @agent.tool
        async def list_slash_commands(ctx: RunContext[Deps]) -> str:
            """List the user's existing slash commands (so you can avoid
            name collisions before calling create_sc, or find the right
            command to edit/delete).
            """
            import json as _json
            result = await sc_list(ctx.deps.user_id or "")
            return _json.dumps(result)

        # ----------------------------------------------------- env var tools
        # Let the AI manage the user's environment variables. When the user
        # has a Hopx API key set, every mutation also rewrites the .env file
        # in their Hopx sandbox — the AI can then read_file(".env") to use
        # those credentials when running code on the user's behalf.

        @agent.tool
        async def set_env(ctx: RunContext[Deps], args: SetEnvArgs) -> str:
            """Create or update an environment variable for the user.

            Use this when the user asks you to save a credential, API key, or
            any config value the AI should reuse later. The value is encrypted
            at rest (when is_secret=true) and synced to the user's Hopx
            sandbox as a .env file so future code executions can read it.

            Args:
                args: {name, value, is_secret?} — name is UPPER_SNAKE_CASE,
                    value is the raw string, is_secret (default true) controls
                    whether the UI masks the value.
            """
            import json as _json
            result = await env_set(ctx.deps.user_id or "", args)
            return _json.dumps(result)

        @agent.tool
        async def delete_env(ctx: RunContext[Deps], args: DeleteEnvArgs) -> str:
            """Delete an environment variable by name.

            Args:
                args: {name} — the UPPER_SNAKE_CASE name of the var to remove.
            """
            import json as _json
            result = await env_delete(ctx.deps.user_id or "", args)
            return _json.dumps(result)

        @agent.tool
        async def list_env(ctx: RunContext[Deps]) -> str:
            """List the user's environment variables.

            Secret values are masked; plain values are returned in full. Use
            this to see what credentials the user has already saved before
            asking them to re-supply one.
            """
            import json as _json
            result = await env_list(ctx.deps.user_id or "")
            return _json.dumps(result)

    def _register_custom_tools(self, agent: Agent[Deps, str]) -> None:
        """Register each user-defined custom tool on the agent.

        Two impl flavours:
          * ``http_webhook`` — POST args to the URL, return the response body.
          * ``python_snippet`` — exec the snippet in a sandbox with the args
            as kwargs and return ``str(result)``.
        """
        import textwrap

        for ct in self.custom_tools:
            name = ct.get("name")
            description = ct.get("description") or "Custom user-defined tool."
            impl_kind = ct.get("impl_kind", "http_webhook")
            http_url = ct.get("http_url")
            http_headers = ct.get("http_headers") or {}
            python_source = ct.get("python_source") or ""

            if not name:
                continue

            # Closure-capture per-iteration values.
            def _make_tool(_name: str, _desc: str, _kind: str, _url: str | None, _headers: dict, _src: str):
                async def _handler(ctx: RunContext[Deps], **kwargs: Any) -> str:
                    if _kind == "http_webhook":
                        import httpx
                        if not _url:
                            return "Error: http_webhook tool has no URL configured"
                        try:
                            async with httpx.AsyncClient(timeout=30.0) as client:
                                resp = await client.post(
                                    _url,
                                    json=kwargs,
                                    headers={k: str(v) for k, v in _headers.items()},
                                )
                                text = resp.text
                                if len(text) > 64_000:
                                    text = text[:64_000] + "\n… (truncated)"
                                return text
                        except Exception as exc:
                            return f"Error calling {_url}: {exc}"
                    elif _kind == "python_snippet":
                        # Run the snippet in the pydantic-monty sandbox so it
                        # can't break the agent process. The snippet receives
                        # ``kwargs`` as a dict and may ``return`` a value.
                        try:
                            indented_src = textwrap.indent(_src, "    ") if _src else ""
                            sandbox_src = (
                                f"_args = {kwargs!r}\n"
                                f"def _user_fn():\n{indented_src}\n"
                                f"result = _user_fn()\n"
                                f"print(repr(result))"
                            )
                            result = await run_python_code(sandbox_src)
                            return result
                        except Exception as exc:
                            return f"Error running snippet: {exc}"
                    return f"Error: unknown impl_kind {_kind!r}"

                _handler.__name__ = _name
                _handler.__doc__ = _desc
                return _handler

            try:
                handler = _make_tool(name, description, impl_kind, http_url, http_headers, python_source)
                agent.tool(handler)
            except Exception:
                logger.warning("Failed to register custom tool %s", name, exc_info=True)

    @staticmethod
    def _build_model_history(
        history: list[dict[str, str]] | None,
    ) -> list[ModelRequest | ModelResponse]:
        model_history: list[ModelRequest | ModelResponse] = []
        for msg in history or []:
            if msg["role"] == "user":
                model_history.append(ModelRequest(parts=[UserPromptPart(content=msg["content"])]))
            elif msg["role"] == "assistant":
                model_history.append(ModelResponse(parts=[TextPart(content=msg["content"])]))
            elif msg["role"] == "system":
                model_history.append(ModelRequest(parts=[SystemPromptPart(content=msg["content"])]))
        return model_history

    @property
    def agent(self) -> Agent[Deps, str]:
        if self._agent is None:
            self._agent = self._create_agent()
        return self._agent

    async def run(
        self,
        user_input: str,
        history: list[dict[str, str]] | None = None,
        deps: Deps | None = None,
    ) -> tuple[str, list[ToolCallPart | ToolReturnPart], Deps]:
        agent_deps = deps if deps is not None else Deps()

        logger.info("Running agent with user input: %s...", user_input[:100])
        result = await self.agent.run(
            user_input,
            deps=agent_deps,
            message_history=self._build_model_history(history),
        )

        tool_events: list[ToolCallPart | ToolReturnPart] = []
        for message in result.all_messages():
            if hasattr(message, "parts"):
                for part in message.parts:
                    if isinstance(part, (ToolCallPart, ToolReturnPart)):
                        tool_events.append(part)

        logger.info("Agent run complete. Output length: %s chars", len(result.output))

        return result.output, tool_events, agent_deps

    async def iter(
        self,
        user_input: str,
        history: list[dict[str, str]] | None = None,
        deps: Deps | None = None,
    ) -> AsyncGenerator[Any, None]:
        agent_deps = deps if deps is not None else Deps()

        async with self.agent.iter(
            user_input,
            deps=agent_deps,
            message_history=self._build_model_history(history),
        ) as run:
            async for event in run:
                yield event


def get_agent(
    model_name: str | None = None,
    thinking_effort: str | None = None,
    temperature: float | None = None,
    todo_capability: "TodoCapability | None" = None,
    provider_base_url: str | None = None,
    provider_api_key: str | None = None,
    provider_model_type: Literal["chat", "responses"] = "chat",
    provider_tools_enabled: bool = True,
    system_prompt: str | None = None,
    user_skills_dir: Path | None = None,
    custom_tools: list[dict[str, Any]] | None = None,
    mcp_servers: list[dict[str, Any]] | None = None,
) -> AssistantAgent:
    return AssistantAgent(
        model_name=model_name,
        thinking_effort=thinking_effort,
        temperature=temperature,
        todo_capability=todo_capability,
        provider_base_url=provider_base_url,
        provider_api_key=provider_api_key,
        provider_model_type=provider_model_type,
        provider_tools_enabled=provider_tools_enabled,
        system_prompt=system_prompt,
        user_skills_dir=user_skills_dir,
        custom_tools=custom_tools,
        mcp_servers=mcp_servers,
    )


def _build_mcp_toolset(server: dict[str, Any]) -> Any:
    """Build a pydantic-ai MCP toolset from a stored server config.

    Returns ``None`` when the ``pydantic-ai-mcp`` extra isn't installed or
    the transport is unknown — the caller logs and moves on.
    """
    transport = (server.get("transport") or "").lower()
    try:
        # pydantic-ai exposes MCP toolsets via the `pydantic_ai.mcp` module.
        from pydantic_ai.mcp import MCPServerStdio, MCPServerSSE, MCPServerStreamableHTTP  # type: ignore
    except ImportError:
        try:
            # Older location.
            from pydantic_ai.toolsets import MCPServerStdio, MCPServerSSE, MCPServerStreamableHTTP  # type: ignore
        except ImportError:
            logger.warning(
                "pydantic-ai MCP extra not installed — MCP server '%s' will be ignored",
                server.get("name"),
            )
            return None

    if transport == "stdio":
        return MCPServerStdio(
            command=server.get("command") or "",
            args=list(server.get("args") or []),
            env=dict(server.get("env") or {}),
        )
    if transport == "sse":
        return MCPServerSSE(
            url=server.get("url") or "",
            headers=dict(server.get("headers") or {}),
        )
    if transport == "streamable_http":
        return MCPServerStreamableHTTP(
            url=server.get("url") or "",
            headers=dict(server.get("headers") or {}),
        )
    return None


async def run_agent(
    user_input: str,
    history: list[dict[str, str]],
    deps: Deps | None = None,
) -> tuple[str, list[ToolCallPart | ToolReturnPart], Deps]:
    agent = get_agent()
    return await agent.run(user_input, history, deps)
