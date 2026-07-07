# Agent Chat App — Worklog

This file tracks what's been done and what's pending. The previous coding
agent errored out mid-stream; this worklog picks up from a fresh clone.

## ⚠️ SECURITY — TOKENS WERE EXPOSED

The user pasted the following tokens in plain text in the original IM chat:

| Service | Token (first 12 chars) |
|---------|------------------------|
| Vercel  | `vcp_05kgvjqz…` |
| GitHub  | `ghp_yLrL5VrF…` |
| HuggingFace | `hf_abmgCTLu…` |

**These must be rotated/replaced by the user before continuing.** The tokens
above were used to deploy the current state of the app but should not be
reused going forward.

## Live deployment

| Component | URL |
|-----------|-----|
| Frontend (Vercel) | https://frontend-wheat-zeta-47.vercel.app |
| Backend (HF Space) | https://normieebroo-agent-chat-app.hf.space |
| GitHub repo | https://github.com/AkshayCoder48/agent-chat-app |
| HF Space repo | https://huggingface.co/spaces/NormieeBroo/agent-chat-app |

## What was done in this session

### 1. Repo bootstrap
- Cloned `vstorm-co/full-stack-ai-agent-template` (cookiecutter template)
- Generated `agent_chat_app/` with cookiecutter, billing/credits/marketing stripped
- Enabled: skills, todos, charts, code execution, websockets, file storage, RAG (pgvector), web search, web fetch
- Pushed baseline to a fresh GitHub repo (`AkshayCoder48/agent-chat-app`)

### 2. Frontend deployment (Vercel)
- Fixed two cookiecutter template bugs:
  - `research-panel.tsx` references `useResearchStore` / `useChatModeStore` but
    the stores are only generated when `enable_deep_research` / `enable_subagents`
    are true. Added stub stores (`research-store.ts`, `chat-mode-store.ts`) so
    the build compiles.
  - `use-chat.ts` was missing `ResearchTodo` and `useResearchStore` imports.
- Vercel project: `agent-chat-app` (`prj_Zvq8hnXi8VNshBfCXpIYCk8kOc3d`)
- Set env vars: `BACKEND_URL`, `BACKEND_WS_URL`, `NEXT_PUBLIC_AUTH_ENABLED`,
  `NEXT_PUBLIC_RAG_ENABLED`, `NEXT_PUBLIC_SITE_URL`
- Production URL: `https://frontend-wheat-zeta-47.vercel.app`

### 3. Backend deployment (HF Space)
- Wiped previous (errored) state of the HF Space
- Pushed a clean self-contained Docker setup:
  - `Dockerfile` — bundles PostgreSQL inside the container (single-stage build)
  - `entrypoint.sh` — initializes Postgres, runs Alembic migrations, seeds
    admin, starts FastAPI on port 7860
  - When `POSTGRES_HOST` is set to anything other than localhost, the
    entrypoint skips the bundled Postgres and connects to the external one
- Set HF Space secrets: `SECRET_KEY`, `API_KEY`, `CORS_ORIGINS`,
  `ENVIRONMENT=production`, `DEBUG=false`, `SEED_ADMIN_EMAIL`,
  `SEED_ADMIN_PASSWORD`
- HF Space: `NormieeBroo/agent-chat-app` (Docker SDK, port 7860)

### 4. Config settings section + custom AI providers (per convo request)
**Backend:**
- New `AIProvider` model (`backend/app/db/models/ai_provider.py`):
  - `id`, `user_id`, `name`, `base_url`, `api_key_encrypted`, `models` (JSONB), `is_active`
- Alembic migration `0025_create_ai_providers`
- Repository (`backend/app/repositories/ai_provider.py`):
  - Encrypts API keys at rest using Fernet + `settings.SECRET_KEY`
- Service (`backend/app/services/ai_provider.py`):
  - CRUD + `test()` method that sends a minimal `/v1/chat/completions` request
- Schemas (`backend/app/schemas/ai_provider.py`): `AIProviderCreate`,
  `AIProviderUpdate`, `AIProviderRead`, `AIProviderList`, `AIProviderTestResult`
- API endpoints (`/api/v1/ai-providers`):
  - `GET /` — list user's providers
  - `POST /` — create
  - `PATCH /{id}` — update (send `api_key=""` to clear)
  - `DELETE /{id}` — delete
  - `POST /{id}/test` — verify provider is reachable
- `/agent/models` endpoint now also returns `providers` array (with
  `has_api_key` flag — never the actual key)

**Frontend:**
- New `Settings → Config` page (`frontend/src/app/[locale]/(dashboard)/settings/config/page.tsx`):
  - Add provider (name, base URL, optional API key)
  - Add/remove model IDs per provider
  - Toggle active/inactive
  - Test connection button with inline status display
  - Delete with confirmation dialog
  - Hopx sandbox API key input (browser-only for now)
  - "Other API keys" placeholder (Tavily, embeddings — backend wired in follow-up)
- `ChatControls` model picker now renders:
  - Default / built-in models
  - User's custom providers (grouped, with model IDs)
  - "No key" badge when provider has no API key set
  - "Add an AI provider in Settings → Config" link when both lists are empty

### 5. Settings nav reorganization (per convo request)
- Removed "Notifications" from settings nav
- Added "Config", "Skills", "MCPs", "Plugins" tabs
- Created placeholder pages for Skills / MCPs / Plugins (ClawHub catalog
  integration is a follow-up task)
- Updated `ROUTES` constants, `settings-nav.tsx`, `settings/layout.tsx`
- Added Settings link to sidebar nav (replacing bottom MobileTabBar)

### 6. Removed bottom MobileTabBar (per convo request)
- Removed `<MobileTabBar />` from dashboard layout
- Removed `pb-20` bottom padding (was for the bar)
- Sidebar now includes Settings link for mobile users

### 7. Fix HF Space BUILD_ERROR + RUNTIME_ERROR (current session)

**Symptom:** frontend returned "Internal server error" / 503 when calling
the backend. HF Space was stuck in `BUILD_ERROR`, then `RUNTIME_ERROR`.

**Root cause #1 — Build failure:**
`RUN chmod +x /entrypoint.sh` ran *after* `USER appuser`, but the file
was owned by root (COPY runs as root). chmod failed with
`Operation not permitted` and the build exited 1.

**Fix #1 (Dockerfile):** moved `COPY entrypoint.sh` + `chmod +x` to
*before* the `USER appuser` directive, then `chown` the file so the
runtime can execute it as appuser.

**Root cause #2 — Runtime failure:**
HF Spaces containers ship with a small `/dev/shm` (64MB). Postgres'
default `posix` dynamic shared memory type + `shared_buffers=128MB`
couldn't allocate, so `pg_ctl start` exited with
`could not start server`.

**Fix #2 (entrypoint.sh):**
- `dynamic_shared_memory_type=mmap` (avoids /dev/shm)
- `shared_buffers=32MB`, `max_connections=20`, `work_mem=4MB`
- `unix_socket_directories=/tmp` (default dir not always writable)
- dump `postgres.log` on pg_ctl failure AND on ready-check timeout

### 8. Fix Vercel frontend env vars (frontend couldn't reach backend)

**Symptom:** User reported `{"detail":"Not Found"}` from the HF Space URL.
After HF Space was healthy, the **frontend** was still broken because
it had zero env vars on Vercel — every API call defaulted to
`http://localhost:8000` and failed.

**Root cause:** Previous session set env vars on the wrong Vercel project.
The production URL `frontend-wheat-zeta-47.vercel.app` is aliased to the
`frontend` project (`prj_A3husicAn66zuu8Y4skrwX7PHdps`), but env vars
were set on the `agent-chat-app` project (`prj_Zvq8hnXi8VNshBfCXpIYCk8kOc3d`)
which has no production alias.

**Fix:** Set the same 7 env vars on the `frontend` project and redeploy:
- `BACKEND_URL=https://normieebroo-agent-chat-app.hf.space`
- `BACKEND_WS_URL=wss://normieebroo-agent-chat-app.hf.space`
- `NEXT_PUBLIC_API_URL=https://normieebroo-agent-chat-app.hf.space`
- `NEXT_PUBLIC_WS_URL=wss://normieebroo-agent-chat-app.hf.space`
- `NEXT_PUBLIC_AUTH_ENABLED=true`
- `NEXT_PUBLIC_RAG_ENABLED=true`
- `NEXT_PUBLIC_SITE_URL=https://frontend-wheat-zeta-47.vercel.app`

**Verification:**
- HF Space stage: `RUNNING`
- `/api/v1/health` → `200 {"status":"healthy"}`
- `/api/v1/agent/models` → `401` (expected — auth required, server healthy)
- Frontend (Vercel): `https://frontend-wheat-zeta-47.vercel.app/` → `200`
- Frontend → backend proxy `/api/auth/login` → `401 {"detail":"Login failed"}`
  (real FastAPI responding, not localhost)
- Frontend → backend proxy `/api/v1/agent/models` → `401` from FastAPI
  (real backend responding)

### 9. Big backlog batch — backend + frontend fixes

**Backend (HF Space + GitHub repo):**

- **Fix `FunctionToolResultEvent has no attribute result`** —
  pydantic-ai 1.x puts the result payload on `tool_event.part`
  (a `ToolReturnPart | RetryPromptPart`), NOT `tool_event.result`.
  Updated `_stream_tool_events` in `agent_session.py`.

- **Fix undefined `todo_cap` reference** — `get_agent()` was called
  with `todo_capability=todo_cap` but `todo_cap` was never defined in
  the module, causing a `NameError` on every agent turn. Removed.

- **Route chat to user's selected provider** — when the WS frame
  carries `provider_id`, `agent_session.py` looks up the provider in
  the DB, decrypts its API key, and passes `base_url` + `api_key` to
  `get_agent()` → `_build_model()` → `OpenAIProvider(base_url=…)`.
  The chat request now goes to the user's provider (OpenRouter, Groq,
  Ollama, vLLM, LM Studio, …) instead of the server default.

- **Inject user_id into agent Deps** — tools that need the current
  user (e.g. `list_chats`) were crashing with "no user context".
  `Deps` now carries `user_id` + `user_name` from the WS session.

- **Fix "Input should be a valid array" on question card** — some
  providers serialize the `questions` array as a JSON string with
  leading whitespace. `ask_user_tool.py` now has `parse_questions()`
  that coerces strings/dicts/scalars into a list of `QuestionItem`,
  dropping bad items instead of crashing the whole turn.

- **`/agent/models` no longer returns built-in model list** — the
  chat picker should show only models the user explicitly added via
  Settings → Config. Returns `models: []` + the default name.

**Frontend (GitHub repo + Vercel):**

- **Add `/api/ai-providers` proxy routes** (root cause of "request
  failed" when adding a provider) — the Config page calls
  `apiClient.post('/ai-providers')` which hits `/api/ai-providers`
  on Next.js, but no proxy route existed. Added:
  - `/api/ai-providers/route.ts` (GET, POST)
  - `/api/ai-providers/[provider_id]/route.ts` (PATCH, DELETE)
  - `/api/ai-providers/[provider_id]/test/route.ts` (POST)

- **Wire `provider_id` through the WS frame** — `use-chat.ts`:
  added `providerIdRef` + `setProviderId()`; payload now includes
  `provider_id` when set. `chat-container.tsx`: passes `setProviderId`
  to `ChatUI`; `ChatControls.onProviderSelect` flows the provider id
  up to the chat layer.

- **Fix prompt context leaking between chats** — when switching
  conversations, reset `model` + `providerId` refs so they don't
  carry over into the new chat's first message.

- **Fade-in animation on streaming AI output** — added `.stream-fade`
  CSS class (opacity + blur ramp) and applied it to the assistant
  text bubble while streaming.

- **Sidebar slide-in animation CSS** — added `.slide-in-left` CSS
  class (translateX + blur ramp) for sidebar / sheet panel
  transitions.

**Verification:**
- HF Space: `RUNNING`, `/api/v1/health` → 200
- Frontend: `https://frontend-wheat-zeta-47.vercel.app/` → 200
- `/api/ai-providers` proxy → 401 (was "Request failed" before)
- `/api/v1/agent/models` proxy → 401 (backend reachable)

## What's still pending (follow-up sessions)

The convo.txt contains 50+ feature requests and bug fixes. Below is the
prioritized backlog. Items are grouped by area and marked with their
original convo priority.

### Backend — Agent / Pydantic AI
- [ ] **Fix `'FunctionToolResultEvent' object has no attribute 'result'`** —
  this is a pydantic-ai version issue. Likely needs pinning a different
  version of `pydantic-ai` or updating tool-call event handling in
  `backend/app/services/agent_session.py`.
- [ ] **Render `reasoning_content` in chat responses** — many OpenAI-compatible
  providers return `delta.reasoning_content` (e.g. DeepSeek, G4F). The frontend
  needs a separate "thinking" panel that streams this. Backend may need to
  forward the field through the WebSocket.
- [ ] **Don't mandate reasoning_content** — make both parsers (with and
  without `reasoning_content`) available. Responses should generate fine
  without reasoning content.
- [ ] **G4F tool calling** — G4F supports tool calling for some models but
  the current implementation returns "upstream returned 403". Investigate
  the G4F tool-call protocol.
- [ ] **AI provider 404 errors** — some providers return 404 on chat
  completions. Investigate which URLs are wrong (likely a `/v1/` prefix
  issue — the test endpoint already handles this, but the actual chat
  session may not).
- [ ] **Make the agent use the user-selected provider/model** — currently
  the agent uses `settings.AI_MODEL` + `settings.OPENAI_API_KEY`. Need to
  look up the user's selected provider from the DB and route the chat
  request to that provider's `base_url` with the user's API key.
- [ ] **Edit system prompt from settings** — add a settings page where
    users can override the agent's system prompt.

### Backend — Tools (per convo)
- [ ] `list_chat` tool — list all chat titles for the current user
- [ ] `read_chat` tool — list messages of a chat as a "file" (not as
  user/assistant context) so the AI can read past conversations
- [ ] `create_tool`, `edit_tool`, `delete_tool` — let the AI define its
  own tools dynamically (no "unknown tool" error when invoked)
- [ ] `create_chart` tool (chart rendering — backend scaffolding exists)
- [ ] `read_skill` tool — read a skill's `SKILL.md` content
- [ ] `read_file`, `write_file`, `create_file`, `edit_file`, `delete_file`
- [ ] `create_folder`, `edit_folder`, `delete_folder`
- [ ] `run_terminal` — execute shell commands in the sandbox
- [ ] Fix `run_terminal() takes 1 positional argument but 2 were given`
- [ ] Fix `file_create() takes from 1 to 2 positional arguments but 3 were given`
- [ ] `list_chats` — "Cannot list chats — no user context" — the tool
  needs to receive the user_id from the agent session

### Backend — Hopx sandbox (replaces E2B / Beam)
- [ ] Implement Hopx sandbox integration using `@computesdk/hopx` (JS SDK)
  or Python equivalent
- [ ] Replace `backend/app/agents/tools/file_tools.py` Beam SDK usage with Hopx
- [ ] Update `Dockerfile` to install Hopx SDK
- [ ] Add `HOPX_API_KEY` to env vars (read from user's stored config, not
  a global env var)
- [ ] Implement file persistence — currently files are lost on sandbox
  restart. Need either persistent storage or a way to sync to the user's
  HF Space `/data` directory.
- [ ] Auto-update file sidebar when AI uses file ops tools (WebSocket
  events from the sandbox)

### Backend — Skills & MCPs
- [ ] Wire up ClawHub catalog API (`https://clawhub.ai/skills?sort=downloads`)
- [ ] Install skill from catalog (download .zip, extract to `/skills/<name>/`)
- [ ] Upload SKILL.md or .zip — extract .zip into a folder named after the
  .zip with the extension stripped
- [ ] Make skills auto-adaptive — when a task matches a skill's
  capabilities, the AI should automatically use the skill (not just
  "see the name")
- [ ] Fix "fake SKILL.md" bug — currently uploaded skills show only a
  generic stub instead of the actual skill content
- [ ] Connect MCP catalog provider (one-click setup)
- [ ] Add MCP CRUD endpoints

### Backend — Tool call streaming
- [ ] Stream tool call output in real-time (currently the entire output
  appears at once after the tool finishes). Requires WebSocket changes
  to stream partial tool output.

### Frontend — UI/UX (per convo)
- [ ] **File browser sidebar** (right side, chat only) — context-aware
  with file/folder ops tools. Currently does not exist.
- [ ] **Fix file sidebar not opening** — likely a CSS / `hidden lg:block`
  issue (needs investigation; the sidebar component doesn't exist yet)
- [ ] **Real-time streaming of tool call output** — see backend item
- [ ] **Fade-in animation on AI output** (per word or letter)
- [ ] **Sidebar motion blur / hover / slide animations** — currently
  sidebars open suddenly with no transition
- [ ] **Remove todo list component from UI when fully completed**
- [ ] **Fix question card validation error** — `Input should be a valid
  array`. The `questions` field is being sent as a JSON string instead
  of an array. Pydantic validation rejects it. Fix in
  `backend/app/agents/tools/ask_user_tool.py` (parse the JSON string
  before validation) or in the frontend (send as an array, not a string).
- [ ] **Add UI render for todos** (like the questions card) — visible
  before answering
- [ ] **File upload from prompt box** — show file extension icon + name
  + size as a chip; save to Hopx sandbox `/uploads/` folder
- [ ] **File upload not saving to Hopx** — wire up
- [ ] **Download files/folders from file sidebar**
- [ ] **Fix "This section failed to load" on cut button of todo**
- [ ] **Fix chat UI being hidden under header** — content scrolls under
  the sticky header
- [ ] **Fix prompt context leaking between chats** — when user types in
  one chat then switches, the prompt box content carries over and is
  sent in the wrong chat
- [ ] **Fix `Cannot list chats — no user context`** — see backend item

### Frontend — Registration
- [ ] **Fix "registration failed"** — investigate the error in
  `frontend/src/components/auth/register-form.tsx`

### Frontend — Animations
- [ ] **Smooth slide / motion blur for sidebar opening** — use Framer
  Motion or CSS transitions on `transform` + `opacity`
- [ ] **Fade-in for AI streaming output** — per-token or per-word
  opacity transition

### Backend — Question card fix (convo)
The error was:
```
[{'type': 'list_type', 'loc': ('questions',), 'msg': 'Input should be a valid array', 'input': '\n[{"question": ...'}]
```
The AI is returning `questions` as a JSON-encoded string with leading
whitespace, but the Pydantic schema expects an array. Fix in
`backend/app/agents/tools/ask_user_tool.py`:
```python
# Before validation, if questions is a string, parse it.
if isinstance(data.get("questions"), str):
    data["questions"] = json.loads(data["questions"].strip())
```

### Backend — System prompt enhancement
- [ ] Add info about available skills, MCPs, plugins, and tools to the
  agent's system prompt so the AI can use them without being asked
- [ ] Add usage examples for each skill

## How to pick up

1. Clone the GitHub repo: `git clone https://github.com/AkshayCoder48/agent-chat-app`
2. Clone the HF Space: `git clone https://huggingface.co/spaces/NormieeBroo/agent-chat-app`
3. Set env vars locally (rotate the leaked tokens first!):
   ```
   export GH_TOKEN=...
   export VERCEL_TOKEN=...
   export HF_TOKEN=...
   ```
4. Pick a pending item from the backlog above and start working.

## Files of interest

### Backend
- `backend/app/db/models/ai_provider.py` — AIProvider model
- `backend/app/repositories/ai_provider.py` — CRUD + encryption helpers
- `backend/app/services/ai_provider.py` — service layer + test() method
- `backend/app/api/routes/v1/ai_providers.py` — REST endpoints
- `backend/app/api/routes/v1/agent.py` — `/agent/models` endpoint
- `backend/app/services/agent_session.py` — WebSocket agent session
- `backend/app/agents/tools/` — agent tools (web_search, code_execution, etc.)

### Frontend
- `frontend/src/app/[locale]/(dashboard)/settings/config/page.tsx` — Config page
- `frontend/src/app/[locale]/(dashboard)/settings/{skills,mcps,plugins}/page.tsx` — placeholders
- `frontend/src/components/settings/settings-nav.tsx` — settings nav items
- `frontend/src/components/chat/chat-controls.tsx` — model picker (now provider-aware)
- `frontend/src/components/layout/sidebar.tsx` — sidebar nav
- `frontend/src/app/[locale]/(dashboard)/layout.tsx` — dashboard layout (no more MobileTabBar)

### HF Space
- `Dockerfile` — self-contained backend build
- `entrypoint.sh` — Postgres + Alembic + FastAPI startup
- `README.md` — HF Space YAML front-matter + docs

---

## Session 2 — 2026-07-07 — Todo Tool + Full Backlog Completion

### Todo Tool (priority ask)
- **Backend** `app/agents/todo_integration.py`: `TodoSessionIntegration` wraps `pydantic_ai_todo.TodoCapability` with a per-WS-session `TodoStorage` + `TodoEventEmitter`. Every mutation emits a `todo_event` WS frame to the client (with the full `all_todos` snapshot so the frontend doesn't need to merge events).
- **Backend** `agent_session.py`: instantiates one `TodoSessionIntegration` per session, passes the resulting `TodoCapability` to `get_agent()`, handles `todo_action` frames (`dismiss` / `reset` / `snapshot`), and resets todos on conversation switch.
- **Frontend** `stores/research-store.ts`: real implementation of `applyTodoEvent` / `dismiss` / `reset` (was a no-op stub). Keyed by `currentTurnId` (= conversation id) so multiple chats don't collide.
- **Frontend** `hooks/use-chat.ts`: forwards the new `all_todos` field to the store, requests a `snapshot` on (re)connect so a page reload mid-generation restores the live plan, exposes `sendTodoAction` to the chat UI.
- **Frontend** `components/chat/research-panel.tsx`: rewrote with a "Cut" (Scissors) button — the exact UI the user asked for. Auto-hides when dismissed or when no todos exist.
- **Frontend** `components/chat/chat-container.tsx`: re-enabled `ResearchPanel`, rendered in the SAME slot as `QuestionPrompt` (right above the chat input). Todo tool calls are filtered out of the message transcript so they only show in the panel.
- **Frontend** `lib/agent-step-captions.ts`: added captions for all 9 todo tools so they narrate correctly while running.

### New backend tools (the "missing tools" backlog)
- `app/agents/tools/workspace_tools.py`: `list_files`, `read_file`, `create_file`, `write_file`, `edit_file`, `delete_file`, `create_folder`, `delete_folder`, `send_file`, `send_folder`, `run_terminal`, `list_chats`, `read_chat`. All per-user-scoped under `MEDIA_DIR/workspaces/<user_id>/` with path-escape protection. `run_terminal` uses an allowlist (ls, cat, grep, python3, git, npm, curl, …). All registered in `assistant.py:_register_tools` with the correct `(ctx, ...)` signatures (fixes the "takes 1 positional argument but 2 were given" bug).

### New backend routes
- `agent_settings.py`: `/agent-settings/system-prompt` (GET/PUT/DELETE) + `/agent-settings/sandbox-keys` (GET/PUT). Stores per-user system prompt + encrypted Hopx/Tavily/embeddings keys.
- `mcp_servers.py`: `/mcp-servers` CRUD (GET/POST/PUT/DELETE).
- `custom_tools.py`: `/custom-tools` CRUD + `/custom-tools/catalog` (built-in starter tools).
- `skills.py`: `/skills/installed`, `/skills/catalog` (ClawHub proxy with fallback), `/skills/install/{name}`, `/skills/upload` (.zip + SKILL.md), `/skills/{name}/SKILL.md`.
- `files.py` extended: `/files/workspace/{user_id}/download`, `/download-folder` (zips on the fly), `/list`.
- New migration `0026_user_settings_mcp_tools.py` adds `user_settings`, `mcp_servers`, `custom_tools` tables.

### Agent / parser fixes
- Switched custom providers from `OpenAIResponsesModel` → `OpenAIChatModel` (most third-party OpenAI-compatible providers only support `/v1/chat/completions`, not the Responses API). Fixes the "AI provider 404 errors on chat completions" bug.
- `FunctionToolResultEvent.result` → already using `.part` (was previously fixed).
- `reasoning_content` from DeepSeek/Moonshot is picked up natively by pydantic-ai's OpenAI parser.
- Agent now uses the user's saved system prompt (when enabled) and dynamically injects available skills + MCP servers + custom tools into the prompt.

### MCP wiring at chat time
- `assistant.py:_build_mcp_toolset` builds a pydantic-ai toolset (stdio / SSE / streamable-http) per active MCP server config; `_create_agent` adds each to the agent's toolsets list. Failures are logged but don't break the chat.

### Skills wiring
- Per-user skills directory `MEDIA_DIR/skills/<user_id>/` is loaded by `SkillsToolset` at chat time. The `skills/upload` endpoint extracts `.zip` / saves `SKILL.md` into the user's dir. ClawHub catalog is fetched with a fallback built-in catalog when the API is unreachable.

### Custom tools wiring
- `_register_custom_tools` in `AssistantAgent` registers each active custom tool as an `@agent.tool`. Two impl kinds: `http_webhook` (POST args to URL) and `python_snippet` (sandboxed via `pydantic-monty`).

### Hopx sandbox integration
- `app/agents/tools/hopx_client.py`: REST client for the Hopx API (`/v1/sandboxes`, `/v1/sandboxes/{id}/files`, `/v1/sandboxes/{id}/exec`).
- `workspace_tools.py:_get_hopx_session` lazy-creates a per-user Hopx sandbox on first tool call, caches it for the session. `read_file`, `create_file`, `run_terminal` route through Hopx when the user has set a `HOPX_API_KEY`; otherwise fall back to the local per-user workspace. `destroy_hopx_session` is called on WS shutdown.
- `agent_settings.py` persists the Hopx key encrypted via Fernet (uses `SECRET_KEY`); the frontend Config page saves it server-side.

### UI / animations / chat bugs
- `chat-store.ts`: persists messages to `sessionStorage` keyed by conversation id, so a reload mid-generation restores the in-flight assistant message. `reconcilePersisted` drops stale state on conversation switch.
- `chat-container.tsx`: reconciles persisted state on mount; `setPersistedConversationId` tracks the active conversation.
- `use-chat.ts`: fires a `tool_result` window event with the tool name on every tool completion; `FileSidebar` listens and auto-refreshes when a workspace-mutating tool finishes (create_file, write_file, delete_file, run_terminal, …).
- `globals.css`: added `scroll-padding-top: 5rem` so scroll anchors don't hide under the sticky header.
- `tool-call-card.tsx`: also recognizes `current_datetime` and `web_search` (in addition to the old `get_current_datetime` / `web_search_tool` names).
- `agent-step-captions.ts`: added captions for all new tools (list_files, read_file, create_file, write_file, edit_file, delete_file, create_folder, delete_folder, send_file, send_folder, run_terminal, list_chats, read_chat) and the 9 todo tools.

### Settings pages
- `settings/skills/page.tsx`: full ClawHub catalog grid with install/uninstall, upload .zip / SKILL.md, installed-skills list.
- `settings/mcps/page.tsx`: full CRUD with stdio / SSE / streamable-http transport picker.
- `settings/tools/page.tsx`: full custom-tool editor (HTTP webhook + Python snippet), starter catalog install, parameters JSON schema editor.
- `settings/config/page.tsx`: System Prompt section now persists via `/api/agent-settings/system-prompt`. New `OtherApiKeysSection` for Tavily + embeddings keys. `HopxConfigSection` persists via `/api/agent-settings/sandbox-keys`.
- `settings/plugins/page.tsx`: deprecated, redirects users to Skills + MCPs.
- `settings-nav.tsx` + `settings/layout.tsx`: both now show all 9 tabs (Profile, Account, Config, Slash commands, Skills, MCPs, Tools, Plugins, Appearance) consistently.
- All new frontend proxy routes under `/api/agent-settings/`, `/api/mcp-servers/`, `/api/custom-tools/`, `/api/skills/`.

### Cleanup
- Removed "Upload to KB" button from `quick-actions.tsx` (replaced with Skills link).
- `gpt-5.5` default model → `gpt-4.1-mini` in `config.py`. `/agent/models` now returns `default_provider_id` so the frontend's model picker auto-selects the first user-added provider's first model.

### Known limitations / follow-ups
- Tool streaming: tool *calls* and *results* stream as separate events, but the intermediate output of long-running tools (e.g. `run_terminal` stdout) is not streamed — it appears all at once when the tool returns. True streaming would require each tool to emit progress events via a callback.
- "Registration failed" in production: the route works locally; needs HF Space logs to diagnose. Likely a CORS / env var issue, not a code issue.
- MCP servers: the `pydantic-ai-mcp` extra needs to be installed on the HF Space for the MCP toolsets to actually spin up; without it, `_build_mcp_toolset` logs a warning and the agent just doesn't see those tools.
- Hopx REST endpoints are best-effort guesses (the public Hopx API may differ); the integration is structured so swapping the URL constants in `hopx_client.py` is the only change needed.

### Files created (16)
- `backend/app/agents/todo_integration.py`
- `backend/app/agents/tools/workspace_tools.py`
- `backend/app/agents/tools/hopx_client.py`
- `backend/app/api/routes/v1/agent_settings.py`
- `backend/app/api/routes/v1/mcp_servers.py`
- `backend/app/api/routes/v1/custom_tools.py`
- `backend/app/api/routes/v1/skills.py`
- `backend/app/db/models/user_settings.py`
- `backend/alembic/versions/0026_user_settings_mcp_tools.py`
- `frontend/src/app/api/agent-settings/system-prompt/route.ts`
- `frontend/src/app/api/agent-settings/sandbox-keys/route.ts`
- `frontend/src/app/api/mcp-servers/route.ts`
- `frontend/src/app/api/mcp-servers/[server_id]/route.ts`
- `frontend/src/app/api/custom-tools/{route,[tool_id]/route,catalog/route}.ts`
- `frontend/src/app/api/skills/{installed,catalog,upload}/route.ts`
- `frontend/src/app/api/skills/install/[skill_name]/route.ts`
- `frontend/src/app/api/skills/[skill_name]/route.ts`

### Files modified (12)
- `backend/app/agents/assistant.py` (custom tools, MCP, per-user skills, chat completions API for custom providers)
- `backend/app/agents/prompts.py` (dynamic system prompt builder)
- `backend/app/api/routes/v1/__init__.py` (wire new routers)
- `backend/app/api/routes/v1/agent.py` (default_provider_id, first-user-provider-wins)
- `backend/app/api/routes/v1/files.py` (workspace download endpoints)
- `backend/app/core/config.py` (gpt-4.1-mini default, model list cleanup)
- `backend/app/db/models/__init__.py` (register new models)
- `backend/app/schemas/base.py` (default_provider_id on AgentModelsResponse)
- `backend/app/services/agent_session.py` (todo integration, Hopx teardown, lazy user-extras loading, conversation-switch reset)
- `frontend/src/components/chat/chat-container.tsx` (re-enable ResearchPanel, persisted-state reconcile, todo action wiring)
- `frontend/src/components/chat/file-sidebar.tsx` (auto-refresh on tool_result events)
- `frontend/src/components/chat/message-item.tsx` (filter out todo tool calls)
- `frontend/src/components/chat/research-panel.tsx` (Cut button, real store, dismiss state)
- `frontend/src/components/chat/tool-call-card.tsx` (recognize new tool names)
- `frontend/src/components/dashboard/quick-actions.tsx` (drop Upload to KB)
- `frontend/src/components/settings/settings-nav.tsx` (add Plugins, consistency)
- `frontend/src/hooks/use-chat.ts` (todo action, tool_result window event, snapshot on reconnect)
- `frontend/src/lib/agent-step-captions.ts` (new tool captions)
- `frontend/src/stores/chat-store.ts` (sessionStorage persistence)
- `frontend/src/stores/research-store.ts` (real implementation)
- `frontend/src/app/[locale]/(dashboard)/settings/{config,skills,mcps,tools,plugins,layout}/page.tsx` (full rewrites)
- `frontend/src/app/globals.css` (scroll-padding-top)

---

## reasoning_content UI + non-standard OpenAI-compatible API parser fix

### What
- Frontend: new `reasoning` MessagePart type + `reasoning_delta` WS event
  + `appendReasoningDelta` chat-store action + `ReasoningBlock` component
  (visually identical to `ThinkingBlock` but labeled "Reasoning" and
  bordered dashed to distinguish OpenAI-native thinking from the
  non-standard `reasoning_content` field that some providers stream).
- Backend: new `app/agents/reasoning_transport.py` — a custom
  `httpx.AsyncBaseTransport` that wraps the OpenAI client's HTTP layer for
  custom-provider turns. Two jobs:
    1. **Parser robustness** — drops chunks with empty `choices` (the
       usage-only chunk that g4f.space and similar providers emit at the
       end; pydantic-ai's parser crashes on `choices[0]` lookup there).
    2. **reasoning_content extraction** — strips `delta.reasoning_content`
       (and the shorter `delta.reasoning`) from SSE chunks BEFORE
       pydantic-ai sees them, and emits each delta via a contextvar
       callback so the frontend gets a `reasoning_delta` WS event.
- Backend: `agent_session.process_message` now sets the per-turn reasoning
  callback (bound to the live WebSocket) before the agent run, and clears
  it in a `finally` block. The callback is a no-op for default-OpenAI
  turns (where the transport isn't wired).
- Backend: `assistant._build_model` passes the wrapped httpx client to
  `OpenAIProvider(http_client=...)` only for custom-provider turns.

### Why
- The user reported that AI providers like `g4f.space` return
  OpenAI-shaped SSE but with a final `choices: []` chunk carrying only
  usage data. The existing parser crashed on this. The new transport
  filters those chunks out.
- These providers also stream `delta.reasoning_content` (DeepSeek /
  Moonshot / g4f convention). The user wanted this rendered in a
  separate collapsible block — distinct from OpenAI-native reasoning
  summaries that come through the `Thinking` capability. The new
  `ReasoningBlock` component handles that.
- "Keep the previous parser with this one both should be used" — the
  existing thinking/text parsers are untouched. Both run side-by-side:
  `delta.content` → text bubble, OpenAI-native reasoning → ThinkingBlock,
  `delta.reasoning_content` → ReasoningBlock.

### g4f.space is NOT natively integrated
- Per the user's explicit request, `g4f.space` is NOT added as a
  built-in/native provider. Users can still add it themselves via
  Settings → AI Providers as a custom OpenAI-compatible provider
  (base_url `https://g4f.space/v1`, their `gfs_…` API key, the model
  name from g4f's catalog). The new transport kicks in automatically
  for any custom provider, so the parser fix and reasoning_content
  extraction work for g4f.space and every other non-standard
  OpenAI-compatible API the user plugs in.

### Files modified (5)
- `backend/app/agents/reasoning_transport.py` (new — 234 lines)
- `backend/app/agents/assistant.py` (wrap httpx client for custom providers)
- `backend/app/services/agent_session.py` (bind per-turn reasoning callback)
- `frontend/src/types/chat.ts` (`reasoning` part type, `reasoning_delta` event, `reasoning?: string` on ChatMessage)
- `frontend/src/stores/chat-store.ts` (`appendReasoningDelta` action)
- `frontend/src/hooks/use-chat.ts` (handle `reasoning_delta` event)
- `frontend/src/components/chat/message-item.tsx` (`ReasoningBlock` component + render `reasoning` parts)

---

## fix(parser): buffer-level CRLF normalization — root cause of stuck-at-thinking

### What
- **Root cause of "stuck at thinking" found and fixed.** The
  `ReasoningAwareTransport` was doing CRLF→LF normalization on
  individual httpx chunks, but when chunks arrive at byte boundaries
  (especially 1-byte-at-a-time from some providers/proxies), no
  single chunk ever contains the two-byte sequence `\r\n`. The buffer
  therefore accumulated raw `\r\n\r\n` SSE separators that never
  matched the `b"\n\n"` split pattern, so NO events were ever yielded
  to the OpenAI SDK. The SDK buffered silently waiting for the first
  event, the agent never produced any `text_delta` / `thinking_delta`
  WS frames, and the chat was stuck at "Thinking…" indefinitely.
- Verified with a smoke test (`scripts/test_reasoning_transport.py`
  — but note: this script lives outside the repo, in
  `/home/z/my-project/scripts/`). The test feeds a synthetic
  g4f.space-style stream (CRLF line endings, byte-at-a-time arrival)
  through the transport. **Before the fix: 0 bytes yielded to the
  SDK. After the fix: all events flow through correctly, reasoning
  deltas extracted, usage chunk dropped, [DONE] forwarded.**
- Fix: normalize CRLF on the BUFFER (not on individual chunks). This
  is the only correct approach because SSE chunks can arrive at any
  byte boundary.

### Hopx key save 'Failed to save' fix
- Was hiding the real backend error behind a generic string. Now
  surfaces the actual FastAPI error message via the existing
  `extractBackendErrorMessage` helper, and special-cases 401 with a
  "session expired" message.

### Silent 401 recovery
- Every Settings API route (sandbox-keys, system-prompt, env-vars
  + env-vars/[name]) now uses the new shared `authedBackendFetch`
  helper. On 401 it silently hits `/api/auth/me` (which uses the
  httpOnly refresh_token cookie to mint a new access_token), retries
  the original request once, and forwards the rotated cookie to the
  browser. An expired 15-minute access token no longer bricks every
  save in the Settings UI as long as the 7-day refresh token is
  still valid.

### Other transport hardening
- Forces `Content-Type: text/event-stream` on intercepted responses
  (some providers set `application/json` even for streams, which
  made the OpenAI SDK buffer the whole body).
- Defensively intercepts responses with unknown/missing content-type
  (some proxies strip the header).
- Wraps `_transform_event` in try/except so a single bad event can
  never kill the whole stream — bad events are passed through
  unchanged.
- Drops chunks with `null` choices (not just empty list) — some
  providers send `choices: null` for the usage chunk.

### Files changed (7)
- `backend/app/agents/reasoning_transport.py` (buffer-level CRLF
  normalization, content-type forcing, defensive try/except, null
  choices handling)
- `frontend/src/lib/authed-backend-fetch.ts` (new shared helper for
  401-refresh + real error surfacing)
- `frontend/src/app/api/agent-settings/sandbox-keys/route.ts`
  (uses shared helper)
- `frontend/src/app/api/agent-settings/system-prompt/route.ts`
  (uses shared helper)
- `frontend/src/app/api/agent-settings/env-vars/route.ts`
  (uses shared helper)
- `frontend/src/app/api/agent-settings/env-vars/[name]/route.ts`
  (uses shared helper)
- `frontend/src/app/[locale]/(dashboard)/settings/config/page.tsx`
  (HopxConfigSection + OtherApiKeysSection + SystemPromptSection
  now surface real backend errors instead of "Failed to save")

### Commit
- `5e4b930` on `main` — pushed to GitHub; HF Space + Vercel will
  auto-deploy.
