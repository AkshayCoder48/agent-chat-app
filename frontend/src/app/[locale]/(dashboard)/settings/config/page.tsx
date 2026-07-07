"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Pencil,
  Plus,
  Server,
  Trash2,
  X,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
  Badge,
  Button,
  FormField,
  Input,
  Switch,
} from "@/components/ui";
import { SectionCard } from "@/components/settings/settings-section";
import { apiClient, ApiError } from "@/lib/api-client";

// ---------- Types ----------

interface AIProvider {
  id: string;
  user_id: string;
  name: string;
  base_url: string;
  models: string[];
  is_active: boolean;
  // "chat" -> POST /v1/chat/completions (universal — works with every
  // OpenAI-compatible provider including g4f.space). "responses" -> POST
  // /v1/responses (OpenAI-direct only). Defaults to "chat" so a freshly
  // added provider works out of the box without the user having to think
  // about endpoint shape.
  model_type: "chat" | "responses";
  // When false, NO tools array is sent in the request body. Some providers
  // (notably certain g4f models) reject any request with a tools array via
  // HTTP 403; toggling this off lets the user still chat in text-only mode.
  tools_enabled: boolean;
  has_api_key: boolean;
  created_at: string;
  updated_at: string;
}

interface AIProviderList {
  items: AIProvider[];
  total: number;
}

interface TestResult {
  ok: boolean;
  status_code?: number | null;
  detail?: string | null;
  sample_response?: string | null;
}

interface ProviderDraft {
  name: string;
  base_url: string;
  api_key: string;
  models: string[];
  is_active: boolean;
  model_type: "chat" | "responses";
  tools_enabled: boolean;
}

const EMPTY_DRAFT: ProviderDraft = {
  name: "",
  base_url: "",
  api_key: "",
  models: [],
  is_active: true,
  model_type: "chat",
  tools_enabled: true,
};

// ---------- Page ----------

export default function ConfigSettingsPage() {
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState<ProviderDraft | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiClient.get<AIProviderList>("/ai-providers");
      setProviders(data.items);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to load providers");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // ---------- Handlers ----------

  const startCreate = () => {
    setEditingId(null);
    setDraft({ ...EMPTY_DRAFT });
  };

  const startEdit = (p: AIProvider) => {
    setEditingId(p.id);
    setDraft({
      name: p.name,
      base_url: p.base_url,
      api_key: "", // never pre-fill the key
      models: [...p.models],
      is_active: p.is_active,
      model_type: p.model_type ?? "chat",
      tools_enabled: p.tools_enabled ?? true,
    });
  };

  const cancel = () => {
    setDraft(null);
    setEditingId(null);
  };

  const save = async () => {
    if (!draft) return;
    if (!draft.name.trim()) {
      toast.error("Name is required");
      return;
    }
    if (!draft.base_url.trim()) {
      toast.error("Base URL is required");
      return;
    }
    setSaving(true);
    try {
      const body = {
        name: draft.name.trim(),
        base_url: draft.base_url.trim(),
        api_key: draft.api_key.trim() || null,
        models: draft.models.filter((m) => m.trim()).map((m) => m.trim()),
        is_active: draft.is_active,
        model_type: draft.model_type,
        tools_enabled: draft.tools_enabled,
      };
      if (editingId) {
        await apiClient.patch(`/ai-providers/${editingId}`, body);
        toast.success("Provider updated");
      } else {
        await apiClient.post("/ai-providers", body);
        toast.success("Provider added");
      }
      await load();
      cancel();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to save provider");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await apiClient.delete(`/ai-providers/${id}`);
      toast.success("Provider deleted");
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to delete");
    }
  };

  const toggleActive = async (p: AIProvider, next: boolean) => {
    try {
      await apiClient.patch(`/ai-providers/${p.id}`, { is_active: next });
      setProviders((prev) =>
        prev.map((x) => (x.id === p.id ? { ...x, is_active: next } : x)),
      );
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to update");
    }
  };

  const test = async (p: AIProvider) => {
    setTestingId(p.id);
    setTestResults((prev) => ({ ...prev, [p.id]: { ok: false, detail: "Testing…" } }));
    try {
      const result = await apiClient.post<TestResult>(
        `/ai-providers/${p.id}/test`,
        undefined,
      );
      setTestResults((prev) => ({ ...prev, [p.id]: result }));
      if (result.ok) toast.success(`Provider ${p.name} responded OK`);
      else toast.error(`Provider ${p.name} test failed`);
    } catch (err) {
      const detail = err instanceof ApiError ? err.message : "Request failed";
      setTestResults((prev) => ({ ...prev, [p.id]: { ok: false, detail } }));
      toast.error(detail);
    } finally {
      setTestingId(null);
    }
  };

  // ---------- Render ----------

  return (
    <div className="space-y-6">
      {/* AI Providers section */}
      <SectionCard
        title="AI providers"
        description="Add OpenAI-compatible providers (base URL + optional API key). Then add the model IDs you want exposed in the chat model picker. API keys are encrypted at rest."
        action={
          <Button onClick={startCreate} size="sm">
            <Plus className="h-4 w-4 mr-1.5" />
            Add provider
          </Button>
        }
      >
        {loading ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading…
          </div>
        ) : providers.length === 0 && !draft ? (
          <div className="rounded-xl border border-dashed border-foreground/15 p-8 text-center">
            <Server className="mx-auto h-8 w-8 text-muted-foreground mb-3" />
            <p className="font-medium">No providers configured yet</p>
            <p className="text-sm text-muted-foreground mt-1">
              Add your first AI provider to start chatting. Any OpenAI-compatible
              endpoint works — OpenAI, Groq, Together, OpenRouter, Ollama, vLLM, LM Studio, etc.
            </p>
            <Button onClick={startCreate} className="mt-4" size="sm">
              <Plus className="h-4 w-4 mr-1.5" />
              Add provider
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            {providers.map((p) => (
              <ProviderRow
                key={p.id}
                provider={p}
                onEdit={() => startEdit(p)}
                onDelete={() => void remove(p.id)}
                onToggle={(v) => void toggleActive(p, v)}
                onTest={() => void test(p)}
                testing={testingId === p.id}
                testResult={testResults[p.id]}
              />
            ))}
          </div>
        )}
      </SectionCard>

      {/* Editor dialog (inline panel, not a modal) */}
      {draft && (
        <ProviderEditor
          draft={draft}
          onChange={setDraft}
          editing={!!editingId}
          saving={saving}
          onSave={save}
          onCancel={cancel}
        />
      )}

      {/* Other config sections — placeholders for follow-up sessions */}
      <SectionCard
        title="Hopx sandbox"
        description="Optional — used for running file ops, terminal, and code execution tools inside an isolated cloud sandbox."
      >
        <HopxConfigSection />
      </SectionCard>

      {/* System prompt override */}
      <SystemPromptSection />

      <OtherApiKeysSection />
    </div>
  );
}

// ---------- Other API Keys Section ----------

function OtherApiKeysSection() {
  const [tavily, setTavily] = useState("");
  const [embeddings, setEmbeddings] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch("/api/agent-settings/sandbox-keys");
        if (!res.ok) throw new Error("Failed to load");
        const d = (await res.json()) as {
          hopx_api_key_set?: boolean;
          tavily_api_key_set?: boolean;
          embeddings_api_key_set?: boolean;
        };
        setTavily(d.tavily_api_key_set ? "•••• (set)" : "");
        setEmbeddings(d.embeddings_api_key_set ? "•••• (set)" : "");
      } catch {
        // ignore
      } finally {
        setLoaded(true);
      }
    })();
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      const payload: Record<string, string | null> = {};
      // Only send when the user typed something new (don't clear existing keys
      // when they leave a field blank).
      if (tavily && !tavily.startsWith("••••")) payload.tavily_api_key = tavily.trim();
      if (embeddings && !embeddings.startsWith("••••")) payload.embeddings_api_key = embeddings.trim();
      if (Object.keys(payload).length === 0) {
        toast.info("No changes to save");
        return;
      }
      const res = await fetch("/api/agent-settings/sandbox-keys", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        let msg = "Failed to save — please try again.";
        try {
          const errData = await res.json();
          if (typeof errData?.detail === "string" && errData.detail.trim()) {
            msg = errData.detail;
          } else if (typeof errData?.message === "string" && errData.message.trim()) {
            msg = errData.message;
          }
        } catch {
          // ignore — keep default msg
        }
        if (res.status === 401) {
          msg = "Your session has expired. Please log in again and retry.";
        }
        throw new Error(msg);
      }
      toast.success("API keys saved");
      setTavily("•••• (set)");
      setEmbeddings("•••• (set)");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  if (!loaded) {
    return (
      <SectionCard
        title="Other API keys"
        description="Keys for web search (Tavily) and embeddings. Stored encrypted on the server."
      >
        <div className="flex items-center justify-center py-8 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading…
        </div>
      </SectionCard>
    );
  }

  return (
    <SectionCard
      title="Other API keys"
      description="Keys for web search (Tavily) and embeddings. Stored encrypted on the server; leave blank to keep an existing key."
    >
      <div className="space-y-4">
        <FormField label="Tavily API key" htmlFor="tavily-key">
          <Input
            id="tavily-key"
            type="password"
            value={tavily}
            onChange={(e) => setTavily(e.target.value)}
            placeholder="tvly-…"
          />
        </FormField>
        <FormField label="Embeddings API key" htmlFor="embeddings-key">
          <Input
            id="embeddings-key"
            type="password"
            value={embeddings}
            onChange={(e) => setEmbeddings(e.target.value)}
            placeholder="sk-…"
          />
        </FormField>
        <Button onClick={save} disabled={saving} size="sm">
          {saving && <Loader2 className="h-4 w-4 animate-spin mr-1.5" />}
          Save keys
        </Button>
      </div>
    </SectionCard>
  );
}

// ---------- System Prompt Section ----------

function SystemPromptSection() {
  const [prompt, setPrompt] = useState<string>("");
  const [enabled, setEnabled] = useState<boolean>(false);
  const [defaultPrompt, setDefaultPrompt] = useState<string>("");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch("/api/agent-settings/system-prompt");
        if (!res.ok) throw new Error("Failed to load");
        const d = (await res.json()) as {
          system_prompt?: string | null;
          system_prompt_enabled?: boolean;
          default_system_prompt?: string;
        };
        setPrompt(d.system_prompt ?? "");
        setEnabled(d.system_prompt_enabled ?? false);
        setDefaultPrompt(d.default_system_prompt ?? "");
      } catch {
        // ignore — section just stays at defaults
      } finally {
        setLoaded(true);
      }
    })();
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      const res = await fetch("/api/agent-settings/system-prompt", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          system_prompt: prompt.trim() || null,
          system_prompt_enabled: enabled,
        }),
      });
      if (!res.ok) {
        let msg = "Failed to save — please try again.";
        try {
          const errData = await res.json();
          if (typeof errData?.detail === "string" && errData.detail.trim()) msg = errData.detail;
          else if (typeof errData?.message === "string" && errData.message.trim()) msg = errData.message;
        } catch { /* ignore */ }
        if (res.status === 401) msg = "Your session has expired. Please log in again and retry.";
        throw new Error(msg);
      }
      toast.success("System prompt saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    setSaving(true);
    try {
      const res = await fetch("/api/agent-settings/system-prompt", {
        method: "DELETE",
      });
      if (!res.ok) {
        let msg = "Failed to reset — please try again.";
        try {
          const errData = await res.json();
          if (typeof errData?.detail === "string" && errData.detail.trim()) msg = errData.detail;
          else if (typeof errData?.message === "string" && errData.message.trim()) msg = errData.message;
        } catch { /* ignore */ }
        if (res.status === 401) msg = "Your session has expired. Please log in again and retry.";
        throw new Error(msg);
      }
      setPrompt("");
      setEnabled(false);
      toast.success("Reset to default prompt");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to reset");
    } finally {
      setSaving(false);
    }
  };

  if (!loaded) {
    return (
      <SectionCard
        title="System prompt"
        description="Override the agent's default system prompt for your chats."
      >
        <div className="flex items-center justify-center py-8 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading…
        </div>
      </SectionCard>
    );
  }

  return (
    <SectionCard
      title="System prompt"
      description="Override the agent's default system prompt for your chats. Leave empty to use the built-in default. The agent also automatically learns about your installed skills, MCPs, and custom tools — no need to mention them here."
    >
      <div className="space-y-4">
        <FormField label="Enable custom prompt" htmlFor="agent-prompt-enabled">
          <div className="flex items-center gap-2">
            <input
              id="agent-prompt-enabled"
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="h-4 w-4 rounded border-input"
            />
            <span className="text-sm text-muted-foreground">
              When checked, your custom prompt replaces the default. When
              unchecked, the prompt is saved but the default is used.
            </span>
          </div>
        </FormField>
        <FormField label="System prompt" htmlFor="agent-system-prompt">
          <textarea
            id="agent-system-prompt"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder={`Leave empty to use the default prompt. Write instructions for how the agent should behave in your chats…\n\nDefault prompt:\n${defaultPrompt.slice(0, 500)}…`}
            rows={10}
            maxLength={20000}
            className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 font-mono"
          />
          <p className="text-xs text-muted-foreground mt-1">
            {prompt.length.toLocaleString()} / 20,000 chars
          </p>
        </FormField>
        <div className="flex gap-2">
          <Button onClick={save} disabled={saving} size="sm">
            {saving ? <Loader2 className="h-4 w-4 animate-spin mr-1.5" /> : <CheckCircle2 className="h-4 w-4 mr-1.5" />}
            Save prompt
          </Button>
          <Button onClick={reset} disabled={saving} size="sm" variant="outline">
            Reset to default
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}

// ---------- Sub-components ----------

function ProviderRow({
  provider,
  onEdit,
  onDelete,
  onToggle,
  onTest,
  testing,
  testResult,
}: {
  provider: AIProvider;
  onEdit: () => void;
  onDelete: () => void;
  onToggle: (v: boolean) => void;
  onTest: () => void;
  testing: boolean;
  testResult?: TestResult;
}) {
  return (
    <div className="rounded-xl border border-foreground/10 p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold truncate">{provider.name}</span>
            {provider.has_api_key ? (
              <Badge variant="secondary" className="text-[10px]">key set</Badge>
            ) : (
              <Badge variant="outline" className="text-[10px]">no key</Badge>
            )}
            {!provider.is_active && (
              <Badge variant="outline" className="text-[10px]">inactive</Badge>
            )}
            {provider.model_type === "responses" ? (
              <Badge variant="outline" className="text-[10px] font-mono" title="POST /v1/responses — OpenAI direct only">
                responses
              </Badge>
            ) : (
              <Badge variant="outline" className="text-[10px] font-mono" title="POST /v1/chat/completions — universal">
                chat
              </Badge>
            )}
            {provider.tools_enabled === false && (
              <Badge variant="outline" className="text-[10px]" title="No tools array sent — text-only mode">
                no tools
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5 truncate">{provider.base_url}</p>
        </div>
        <div className="flex items-center gap-2">
          <Switch checked={provider.is_active} onCheckedChange={onToggle} />
          <Button size="sm" variant="ghost" onClick={onEdit}>
            <Pencil className="h-3.5 w-3.5" />
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button size="sm" variant="ghost">
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete provider?</AlertDialogTitle>
                <AlertDialogDescription>
                  This permanently deletes <b>{provider.name}</b> and its
                  stored API key. This action cannot be undone.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={onDelete}>Delete</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      {provider.models.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {provider.models.map((m) => (
            <Badge key={m} variant="outline" className="font-mono text-[10px]">
              {m}
            </Badge>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" onClick={onTest} disabled={testing}>
          {testing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5 mr-1.5" />
          )}
          Test
        </Button>
        {testResult && (
          <div
            className={`flex items-center gap-1.5 text-xs ${
              testResult.ok ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"
            }`}
          >
            {testResult.ok ? (
              <CheckCircle2 className="h-3.5 w-3.5" />
            ) : (
              <XCircle className="h-3.5 w-3.5" />
            )}
            <span className="truncate max-w-md">
              {testResult.ok
                ? `OK${testResult.status_code ? ` (${testResult.status_code})` : ""}${
                    testResult.sample_response ? `: ${testResult.sample_response.slice(0, 80)}` : ""
                  }`
                : testResult.detail || "Failed"}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function ProviderEditor({
  draft,
  onChange,
  editing,
  saving,
  onSave,
  onCancel,
}: {
  draft: ProviderDraft;
  onChange: (next: ProviderDraft) => void;
  editing: boolean;
  saving: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  const [newModel, setNewModel] = useState("");

  const addModel = () => {
    const m = newModel.trim();
    if (!m) return;
    if (draft.models.includes(m)) {
      setNewModel("");
      return;
    }
    onChange({ ...draft, models: [...draft.models, m] });
    setNewModel("");
  };

  return (
    <div className="rounded-xl border border-foreground/15 bg-card p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">{editing ? "Edit provider" : "Add provider"}</h3>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <FormField label="Display name" htmlFor="provider-name">
          <Input
            id="provider-name"
            placeholder="OpenAI / Groq / My Ollama"
            value={draft.name}
            onChange={(e) => onChange({ ...draft, name: e.target.value })}
          />
        </FormField>
        <FormField label="Base URL" htmlFor="provider-base-url">
          <Input
            id="provider-base-url"
            placeholder="https://api.openai.com or http://localhost:11434/v1"
            value={draft.base_url}
            onChange={(e) => onChange({ ...draft, base_url: e.target.value })}
          />
        </FormField>
      </div>

      <FormField
        label="API key (optional)"
        htmlFor="provider-api-key"
        description="Leave blank for local providers (Ollama, vLLM, LM Studio). Stored encrypted."
      >
        <Input
          id="provider-api-key"
          type="password"
          placeholder={editing ? "•••••••• (leave blank to keep existing)" : "sk-…"}
          value={draft.api_key}
          onChange={(e) => onChange({ ...draft, api_key: e.target.value })}
        />
      </FormField>

      <div>
        <label htmlFor="provider-model-input" className="text-sm font-medium">Models</label>
        <p className="text-xs text-muted-foreground mb-2">
          Add the model IDs you want exposed in the chat model picker. Most
          OpenAI-compatible endpoints accept any string the upstream serves.
        </p>
        <div className="flex gap-2">
          <Input
            id="provider-model-input"
            placeholder="gpt-4o / llama-3.1-70b / etc."
            value={newModel}
            onChange={(e) => setNewModel(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addModel();
              }
            }}
          />
          <Button type="button" size="sm" onClick={addModel}>
            <Plus className="h-4 w-4 mr-1" /> Add
          </Button>
        </div>
        {draft.models.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {draft.models.map((m) => (
              <Badge key={m} variant="outline" className="font-mono text-[10px] gap-1">
                {m}
                <button
                  type="button"
                  onClick={() => onChange({ ...draft, models: draft.models.filter((x) => x !== m) })}
                  className="ml-1 hover:text-red-500"
                  aria-label={`Remove ${m}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <Switch
          id="provider-active"
          checked={draft.is_active}
          onCheckedChange={(v) => onChange({ ...draft, is_active: v })}
        />
        <label htmlFor="provider-active" className="text-sm">
          Active (show in chat model picker)
        </label>
      </div>

      {/* API endpoint type — controls whether the agent hits
          /v1/chat/completions (universal, works with every OpenAI-compatible
          provider including g4f.space) or /v1/responses (OpenAI-direct only).
          Defaulting to "chat" is what fixes the stuck-at-thinking bug users
          hit when they pointed the app at g4f.space — that provider doesn't
          implement /v1/responses and the SSE parser hung forever waiting for
          a chunk that never came. */}
      <div>
        <label className="text-sm font-medium">API endpoint type</label>
        <p className="text-xs text-muted-foreground mb-2">
          Most OpenAI-compatible providers (OpenRouter, Groq, Together, Ollama,
          vLLM, LM Studio, g4f.space, …) only support{" "}
          <code className="font-mono">/v1/chat/completions</code>. Use the
          Responses API only when talking to OpenAI directly.
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => onChange({ ...draft, model_type: "chat" })}
            className={`text-left rounded-lg border p-3 transition-colors ${
              draft.model_type === "chat"
                ? "border-primary bg-primary/5 ring-1 ring-primary"
                : "border-foreground/15 hover:border-foreground/30"
            }`}
          >
            <div className="flex items-center gap-2">
              <span
                className={`h-2 w-2 rounded-full ${
                  draft.model_type === "chat" ? "bg-primary" : "bg-muted-foreground/40"
                }`}
              />
              <span className="font-medium text-sm">Chat Completions</span>
            </div>
            <p className="text-xs text-muted-foreground mt-1 ml-4">
              <code className="font-mono">/v1/chat/completions</code> — works
              with all providers
            </p>
          </button>
          <button
            type="button"
            onClick={() => onChange({ ...draft, model_type: "responses" })}
            className={`text-left rounded-lg border p-3 transition-colors ${
              draft.model_type === "responses"
                ? "border-primary bg-primary/5 ring-1 ring-primary"
                : "border-foreground/15 hover:border-foreground/30"
            }`}
          >
            <div className="flex items-center gap-2">
              <span
                className={`h-2 w-2 rounded-full ${
                  draft.model_type === "responses" ? "bg-primary" : "bg-muted-foreground/40"
                }`}
              />
              <span className="font-medium text-sm">Responses API</span>
            </div>
            <p className="text-xs text-muted-foreground mt-1 ml-4">
              <code className="font-mono">/v1/responses</code> — OpenAI direct only
            </p>
          </button>
        </div>
      </div>

      {/* Tool calling toggle — when off, NO tools array is sent in the
          request body. Some providers (notably certain g4f models) reject
          any request that includes a tools array via HTTP 403, which
          surfaces as stuck-at-thinking because the SSE stream never starts.
          With this off the user can still chat in text-only mode. */}
      <div className="rounded-lg border border-foreground/15 p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-medium">Tool calling</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Disable if the provider returns 403 errors on tool calls (some
              g4f / free models). Text-only mode still works for chat — the
              agent just can&apos;t call create_file, run_python, etc.
            </p>
          </div>
          <Switch
            id="provider-tools-enabled"
            checked={draft.tools_enabled}
            onCheckedChange={(v) => onChange({ ...draft, tools_enabled: v })}
          />
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 pt-2 border-t border-foreground/10">
        <Button variant="ghost" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        <Button onClick={onSave} disabled={saving}>
          {saving && <Loader2 className="h-4 w-4 animate-spin mr-1.5" />}
          {editing ? "Save changes" : "Add provider"}
        </Button>
      </div>
    </div>
  );
}

// Hopx config section — persists to backend via /api/agent-settings/sandbox-keys.
// The key is stored encrypted server-side; the localStorage copy is a
// fallback for offline / single-instance dev.
function HopxConfigSection() {
  const [key, setKey] = useState("");
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void (async () => {
      // Show a placeholder when the key is already set on the server.
      try {
        const res = await fetch("/api/agent-settings/sandbox-keys");
        if (!res.ok) return;
        const d = (await res.json()) as { hopx_api_key_set?: boolean };
        if (d.hopx_api_key_set) setKey("•••• (set)");
      } catch {
        // ignore
      }
      const stored =
        typeof window !== "undefined" ? window.localStorage.getItem("hopx_api_key") : null;
      if (stored && !key) setKey(stored);
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      // Only persist when the user typed a new key (not the placeholder).
      if (key && !key.startsWith("••••")) {
        const res = await fetch("/api/agent-settings/sandbox-keys", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ hopx_api_key: key.trim() }),
        });
        if (!res.ok) {
          // Surface the real backend error instead of a generic string.
          let msg = "Failed to save — please try again.";
          try {
            const errData = await res.json();
            if (typeof errData?.detail === "string" && errData.detail.trim()) {
              msg = errData.detail;
            } else if (typeof errData?.message === "string" && errData.message.trim()) {
              msg = errData.message;
            }
          } catch {
            // response had no JSON body — keep the default message
          }
          // Special-case 401: the auto-refresh in the route handler tried
          // and failed, so the user needs to log in again.
          if (res.status === 401) {
            msg = "Your session has expired. Please log in again and retry.";
          }
          throw new Error(msg);
        }
        if (typeof window !== "undefined") {
          window.localStorage.setItem("hopx_api_key", key.trim());
        }
        setKey("•••• (set)");
        setSaved(true);
        toast.success("Hopx key saved");
        setTimeout(() => setSaved(false), 2000);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <AlertTriangle className="h-3.5 w-3.5" />
        <span>
          Optional. When set, the agent routes file/terminal/code-execution
          ops through the Hopx sandbox instead of the local per-user
          workspace. Stored encrypted on the server.
        </span>
      </div>
      <FormField label="Hopx API key" htmlFor="hopx-key">
        <Input
          id="hopx-key"
          type="password"
          placeholder="hopx_live_…"
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
      </FormField>
      <Button size="sm" onClick={save} disabled={saving}>
        {saving ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin mr-1.5" /> Saving…
          </>
        ) : saved ? (
          "Saved ✓"
        ) : (
          "Save"
        )}
      </Button>
    </div>
  );
}
