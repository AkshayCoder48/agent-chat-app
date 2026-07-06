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
