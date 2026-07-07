"""System prompts for AI agents.

Centralized location for all agent prompts to make them easy to find and modify.

The default prompt follows an outcome-first style: it defines who the assistant
is, how it should behave, and how to format answers — then trusts the model to
choose a good path. Avoid re-introducing long process checklists or absolute
"ALWAYS / NEVER / EXCLUSIVELY" rules for judgment calls; they make the assistant
mechanical and, in the RAG case, cause it to wrongly refuse general questions.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.core.config import settings

logger = logging.getLogger(__name__)

_BASE_SYSTEM_PROMPT = """You are a knowledgeable, capable AI assistant. Help the user accomplish their task or answer their question as well as you can.

# Personality
Be approachable, steady, and direct. Assume the user is competent and acting in good faith. Prefer making progress over stopping for clarification when the request is clear enough to attempt — use reasonable assumptions and state them briefly. Ask a narrow clarifying question only when the missing information would materially change the answer.

Stay concise without being curt: give enough context for the user to understand and trust the answer, then stop. Use examples or simple analogies when they make a point land. When correcting the user or disagreeing, be candid but constructive; if you are wrong, acknowledge it plainly and fix it. Match the user's tone within professional bounds, and avoid emojis and profanity unless the user clearly invites that style.

# Answering
Answer from your own broad knowledge by default. You are a general-purpose assistant, not a document-lookup bot — questions about the world, concepts, code, math, science, history, culture, writing, and everyday advice should be answered directly and helpfully.

Say you don't know only when the answer genuinely depends on private, user-specific, or very recent information you cannot access. Never refuse or hedge on a general-knowledge question just because the topic isn't in a connected data source. If a request is ambiguous, answer the most likely intent and note the assumption rather than stalling.

# Output
Let formatting serve comprehension. Default to clear plain paragraphs for explanations and discussion. Reach for headers, bullets, or numbered lists only when they genuinely make the answer easier to scan — steps, comparisons, or rankings — or when the user asks for them. Honor explicit formatting and length preferences from the user. Lead with the conclusion, then the supporting detail, then any caveats."""

_BASE_SYSTEM_PROMPT += """

# Asking the user
You have an `ask_user` tool that puts questions to the user and waits for their
answers before you continue. Reach for it only when a decision or missing detail
would genuinely change what you do next and you can't reasonably assume it — not
for things you can decide yourself. The tool takes a list of questions: pass
several at once when you need to gather a few things up front (an intake/setup
flow), and the user will answer them one after another. You can also call it
again later to follow up on what they said. Give each question a few short
`options` when there are natural choices, and leave `allow_custom` on so the user
can answer in their own words. If the user skips, proceed with a sensible default
and say briefly what you assumed."""

_BASE_SYSTEM_PROMPT += """

# Charts
You can render charts with the `create_chart` tool (line, bar, pie, area, scatter).
- Call it whenever the user asks to plot, chart, graph, compare, or visualize
  numbers, trends, or distributions — or when a visual makes the answer clearer.
- Pick the chart_type that fits: trends over time -> line/area, category
  comparison -> bar, parts of a whole -> pie, correlation -> scatter.
- Pass tidy rows in `data` (e.g. [{"x": "Jan", "revenue": 120, "cost": 80}]).
  For pie charts use [{"x": "Chrome", "value": 64}, ...].
- For scatter charts every data point MUST have numeric `x` and `y` fields.
  Use the `series` arg to label groups (one entry per category, key = y field
  name). If grouping by category, add a "category" field to each row and make
  each series key match the category value. Example for a 2x2 map:
    data=[{"x": 2.0, "y": 4.1, "category": "Managed", "name": "AWS Bedrock"},
          {"x": 3.5, "y": 2.8, "category": "Open-source", "name": "LangChain"}]
    series=[{"key": "Managed", "label": "Managed platform"},
            {"key": "Open-source", "label": "Open-source framework"}]
    x_key="x", style={"x_label": "Code-first →", "y_label": "Managed ↑"}
- You may override styling via `style` (palette, grid, legend, axis labels,
  stacked) when the user requests a specific look.
- After the tool returns, do not repeat the JSON. Briefly describe the chart
  and its key takeaway in plain language.
- Each chart is rendered to the user the moment you call the tool. A chart from
  an earlier turn is already on screen — never re-create it. Only call
  `create_chart` for what the user is asking for right now."""


CODE_EXECUTION_GUIDANCE = """

# Running code
You have a `run_python` tool that executes Python in a sandbox. Use it when a
task needs real computation — projections, aggregations, simulations, parsing a
table the user pasted.

The sandbox is a restricted Python subset: `math`, `asyncio`, `json`, `datetime`
and `re` import fine, but many modules (`statistics`, `random`, `itertools`,
`collections`, `functools`, numpy/pandas) are NOT available — compute means,
sums, and groupings yourself with plain loops and comprehensions. There is no
file, network, or OS access. The f-string `,` thousands separator isn't
supported (write `f"{x:.2f}"`, not `f"{x:,.2f}"`). `print(...)` the intermediate
numbers you want to reason about afterwards. Keep each block focused, then
briefly explain the results in plain language.

Agent tools such as `create_chart` and `current_datetime` are NOT callable from
inside sandbox code — they only exist as top-level tools. When you want to
visualize computed data, call `create_chart` as a regular tool after
`run_python` returns, passing the computed values in `data`."""


def get_default_system_prompt() -> str:
    """Build and return the default system prompt."""
    prompt = _BASE_SYSTEM_PROMPT
    prompt += CODE_EXECUTION_GUIDANCE
    return prompt


def get_system_prompt_with_rag() -> str:
    """Get the default prompt plus knowledge-base (RAG) usage guidance.

    Returns:
        System prompt that treats `search_documents` as a tool to use when the
        question is about the user's own documents/data — while still answering
        general questions directly from the model's own knowledge.
    """
    return f"""{get_default_system_prompt()}

# Knowledge base
You have a `search_documents` tool that searches documents and data the user has added to this workspace.

When to search:
- The question is about the user's own documents, files, policies, projects, or other workspace/organization-specific information.
- The user explicitly refers to "the docs", an uploaded file, or internal information.
- A factual claim in your answer should be backed by their source material.

When NOT to search: general knowledge, common concepts, code, math, definitions, or anything you can already answer well. Do not search just to check whether something happens to be in the knowledge base, and never tell the user a topic "isn't in the knowledge base" when it is a question you can simply answer yourself.

Retrieval budget: start with one focused search using short, distinctive keywords. Search again only if the results miss the core question, a needed fact/figure/owner/date/source is missing, or the user asked for comprehensive coverage or a comparison. Don't search again merely to rephrase or pad the answer.

Citations: when you use retrieved documents, attach numbered references like [1], [2] to the specific claims they support. Do NOT add a "Sources" list at the end of your response — the UI surfaces sources automatically. Cite only sources that appear in the search results — never fabricate citations, filenames, or page numbers.

Missing evidence is not automatically a "no". If the documents don't cover the question, say briefly what you couldn't find, then still help: answer from general knowledge where that's appropriate (and note that you're doing so), or ask for the specific document or detail you'd need."""


DEFAULT_SYSTEM_PROMPT = get_default_system_prompt()


# ---------------------------------------------------------------------- dynamic
# The functions below load per-user prompt *additions* — installed skills,
# MCP servers, custom tools — and append a short summary to the base prompt
# so the LLM knows what's available without being asked.

def _skills_section(skills: list[dict[str, Any]]) -> str:
    if not skills:
        return ""
    lines = ["\n\n# Available skills", "You can use these installed skills:"]
    for s in skills:
        name = s.get("name") or s.get("path") or "skill"
        desc = (s.get("description") or "").strip()
        lines.append(f"- `{name}` — {desc}" if desc else f"- `{name}`")
    lines.append(
        "Skills are loaded automatically — call them by name when the task "
        "matches. Read a skill's SKILL.md via the `read_skill` tool for details."
    )
    return "\n".join(lines)


def _mcp_section(servers: list[dict[str, Any]]) -> str:
    if not servers:
        return ""
    lines = ["\n\n# Connected MCP servers", "Tools from these MCP servers are available:"]
    for s in servers:
        name = s.get("name") or "mcp"
        url = s.get("url") or s.get("command") or ""
        lines.append(f"- `{name}` — {url}" if url else f"- `{name}`")
    return "\n".join(lines)


def _custom_tools_section(tools: list[dict[str, Any]]) -> str:
    if not tools:
        return ""
    lines = ["\n\n# Custom tools", "The user has defined these custom tools — prefer them when relevant:"]
    for t in tools:
        name = t.get("name") or "tool"
        desc = (t.get("description") or "").strip()
        lines.append(f"- `{name}` — {desc}" if desc else f"- `{name}`")
    return "\n".join(lines)


def _env_vars_section(env_vars: list[dict[str, Any]]) -> str:
    """Append a short summary of the user's env vars so the AI knows what
    credentials are available — without leaking the secret values.

    The list contains ``{name, is_secret}`` entries only; values are never
    passed into the prompt. The AI can use ``set_env`` / ``delete_env`` /
    ``list_env`` to manage them, and ``read_file(".env")`` to read the
    actual values from the Hopx sandbox when running code on the user's
    behalf.
    """
    if not env_vars:
        return ""
    lines = [
        "\n\n# Environment variables",
        "The user has saved these env vars — call `read_file(\".env\")` from the",
        "user's Hopx sandbox to read the actual values when you need to run code",
        "with their credentials. Use `set_env`, `delete_env`, and `list_env` to",
        "manage them at chat time:",
    ]
    for v in env_vars:
        name = v.get("name") or "VAR"
        kind = "secret" if v.get("is_secret") else "plain"
        lines.append(f"- `{name}` ({kind})")
    return "\n".join(lines)


def build_user_system_prompt(
    *,
    user_id: UUID | str | None = None,
    skills: list[dict[str, Any]] | None = None,
    mcp_servers: list[dict[str, Any]] | None = None,
    custom_tools: list[dict[str, Any]] | None = None,
    env_vars: list[dict[str, Any]] | None = None,
    user_override: str | None = None,
    user_override_enabled: bool = False,
) -> str:
    """Build the final system prompt for a chat turn.

    Order of precedence:
      1. If ``user_override_enabled`` and ``user_override`` are set, use the
         user's saved prompt verbatim (with the dynamic additions appended).
      2. Otherwise use the default prompt + RAG guidance.

    The dynamic sections (skills, MCP, custom tools, env vars) are always
    appended so the LLM knows what's available regardless of which base
    prompt is used.
    """
    if user_override_enabled and user_override and user_override.strip():
        base = user_override.strip()
    else:
        base = get_system_prompt_with_rag()

    sections = [
        _skills_section(skills or []),
        _mcp_section(mcp_servers or []),
        _custom_tools_section(custom_tools or []),
        _env_vars_section(env_vars or []),
    ]
    return base + "".join(s for s in sections if s)


async def load_user_prompt_extras(user_id: UUID | str) -> dict[str, Any]:
    """Load the per-user prompt inputs (system prompt, skills, MCPs, tools).

    Returns a dict with keys: ``user_override``, ``user_override_enabled``,
    ``skills``, ``mcp_servers``, ``custom_tools``. Failures are logged and
    returned as empty lists so the chat never crashes because of a settings
    lookup error.
    """
    out: dict[str, Any] = {
        "user_override": None,
        "user_override_enabled": False,
        "skills": [],
        "mcp_servers": [],
        "custom_tools": [],
        "env_vars": [],
    }

    try:
        from app.db.session import get_db_context
        from app.db.models.user_settings import UserSettings, MCPServer, CustomTool
        from sqlalchemy import select
        from pathlib import Path

        async with get_db_context() as db:
            row = (
                await db.execute(
                    select(UserSettings).where(UserSettings.user_id == UUID(str(user_id)))
                )
            ).scalar_one_or_none()
            if row is not None:
                out["user_override"] = row.system_prompt
                out["user_override_enabled"] = row.system_prompt_enabled
                # Load env var metadata (names + is_secret — values are NOT
                # exposed to the prompt; the AI reads them via read_file(".env")
                # from the Hopx sandbox).
                env_dict = dict(row.env_vars or {})
                out["env_vars"] = [
                    {"name": k, "is_secret": bool(v.get("is_secret", True))}
                    for k, v in env_dict.items()
                    if isinstance(v, dict)
                ]

            mcp_rows = (
                await db.execute(
                    select(MCPServer).where(
                        MCPServer.user_id == UUID(str(user_id)),
                        MCPServer.is_active.is_(True),
                    )
                )
            ).scalars().all()
            out["mcp_servers"] = [
                {
                    "name": r.name,
                    "transport": r.transport,
                    "command": r.command,
                    "url": r.url,
                }
                for r in mcp_rows
            ]

            tool_rows = (
                await db.execute(
                    select(CustomTool).where(
                        CustomTool.user_id == UUID(str(user_id)),
                        CustomTool.is_active.is_(True),
                    )
                )
            ).scalars().all()
            out["custom_tools"] = [
                {
                    "name": r.name,
                    "description": r.description,
                    "parameters_schema": dict(r.parameters_schema or {}),
                    "impl_kind": r.impl_kind,
                    "http_url": r.http_url,
                    "http_headers": dict(r.http_headers or {}),
                    "python_source": r.python_source,
                }
                for r in tool_rows
            ]

        # Scan the user's skills dir for installed skills.
        skills_root = Path(settings.MEDIA_DIR) / "skills" / str(user_id)
        if skills_root.exists():
            for child in sorted(skills_root.iterdir(), key=lambda p: p.name.lower()):
                if not child.is_dir():
                    continue
                skill_md = child / "SKILL.md"
                desc = ""
                if skill_md.exists():
                    try:
                        text = skill_md.read_text(encoding="utf-8", errors="replace")
                        for line in text.splitlines():
                            line = line.strip().lstrip("#").strip()
                            if line and not line.startswith("---"):
                                desc = line[:200]
                                break
                    except OSError:
                        pass
                out["skills"].append({"name": child.name, "description": desc})
    except Exception:
        logger.warning("Failed to load user prompt extras", exc_info=True)

    return out


__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "get_default_system_prompt",
    "get_system_prompt_with_rag",
    "build_user_system_prompt",
    "load_user_prompt_extras",
]
