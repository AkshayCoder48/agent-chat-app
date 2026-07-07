"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { Button, Input, Label } from "@/components/ui";
import { SectionCard as SettingsSectionCard } from "@/components/settings/settings-section";
import { cn } from "@/lib/utils";

interface EnvVar {
  name: string;
  value: string;
  /** Whether the value is masked (we never receive the raw value from the backend). */
  is_secret: boolean;
  created_at?: string;
  updated_at?: string;
}

interface EnvVarListResponse {
  vars: EnvVar[];
  hopx_synced: boolean;
}

interface EnvVarPayload {
  name: string;
  value: string;
  is_secret?: boolean;
}

/**
 * Coerce arbitrary backend response into an EnvVarListResponse-shaped object.
 * The proxy may pass through error objects ({detail:"..."}) or null when the
 * backend is unreachable — guard against that so the page never crashes.
 */
function toEnvVarList(data: unknown): EnvVarListResponse {
  if (data && typeof data === "object") {
    const obj = data as Record<string, unknown>;
    const vars = Array.isArray(obj.vars) ? (obj.vars as EnvVar[]) : [];
    return {
      vars,
      hopx_synced: Boolean(obj.hopx_synced),
    };
  }
  return { vars: [], hopx_synced: false };
}

const EMPTY_FORM = {
  name: "",
  value: "",
  is_secret: true as boolean,
};

export default function EnvSettingsPage() {
  const [vars, setVars] = useState<EnvVar[]>([]);
  const [hopxSynced, setHopxSynced] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [editingName, setEditingName] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/agent-settings/env-vars");
      if (!res.ok) throw new Error("Failed to load env vars");
      const data = toEnvVarList(await res.json());
      setVars(data.vars);
      setHopxSynced(data.hopx_synced);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSave = async () => {
    const name = form.name.trim();
    if (!name) {
      toast.error("Name is required");
      return;
    }
    if (!/^[A-Z_][A-Z0-9_]*$/.test(name)) {
      toast.error("Name must be UPPER_SNAKE_CASE (A-Z, 0-9, _)");
      return;
    }
    if (!form.value) {
      toast.error("Value is required");
      return;
    }

    setSaving(true);
    try {
      const payload: EnvVarPayload = {
        name,
        value: form.value,
        is_secret: form.is_secret,
      };
      const url = editingName
        ? `/api/agent-settings/env-vars/${encodeURIComponent(editingName)}`
        : "/api/agent-settings/env-vars";
      const method = editingName ? "PUT" : "POST";
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(err.detail ?? "Failed to save env var");
      }
      const data = (await res.json()) as { hopx_synced?: boolean };
      toast.success(editingName ? `Updated ${name}` : `Added ${name}`, {
        description: data.hopx_synced
          ? "Synced to Hopx sandbox"
          : undefined,
      });
      setForm({ ...EMPTY_FORM });
      setEditingName(null);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (v: EnvVar) => {
    setEditingName(v.name);
    setForm({ name: v.name, value: "", is_secret: v.is_secret });
    // Scroll to top so the form is visible.
    if (typeof window !== "undefined") {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  const handleDelete = async (v: EnvVar) => {
    if (!confirm(`Delete env var ${v.name}?`)) return;
    try {
      const res = await fetch(
        `/api/agent-settings/env-vars/${encodeURIComponent(v.name)}`,
        { method: "DELETE" },
      );
      if (!res.ok) throw new Error("Failed to delete");
      toast.success(`Removed ${v.name}`);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const handleCancelEdit = () => {
    setForm({ ...EMPTY_FORM });
    setEditingName(null);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <KeyRound className="h-6 w-6" />
          Environment variables
        </h1>
        <p className="text-muted-foreground mt-1">
          Secret values the AI can read at chat time. When you set your first
          env var, a <code>.env</code> file is auto-created in your Hopx
          sandbox so the AI can run code with your credentials.
        </p>
      </div>

      <SettingsSectionCard
        title={editingName ? `Edit ${editingName}` : "Add an env var"}
        description="Use UPPER_SNAKE_CASE names. Secret values are encrypted at rest and never sent back to the browser — the AI reads them via the sandbox .env file."
      >
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="env-name" className="text-xs uppercase">
                Name
              </Label>
              <Input
                id="env-name"
                value={form.name}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    name: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ""),
                  }))
                }
                placeholder="OPENAI_API_KEY"
                className="font-mono"
                disabled={!!editingName}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="env-secret" className="text-xs uppercase">
                Type
              </Label>
              <select
                id="env-secret"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={form.is_secret ? "secret" : "plain"}
                onChange={(e) =>
                  setForm((f) => ({ ...f, is_secret: e.target.value === "secret" }))
                }
              >
                <option value="secret">Secret (masked)</option>
                <option value="plain">Plain (visible)</option>
              </select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="env-value" className="text-xs uppercase">
              Value
            </Label>
            <Input
              id="env-value"
              value={form.value}
              onChange={(e) => setForm((f) => ({ ...f, value: e.target.value }))}
              placeholder={editingName ? "Enter new value to replace" : "Enter value"}
              type={form.is_secret ? "password" : "text"}
              className="font-mono"
            />
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={handleSave} disabled={saving}>
              {saving ? (
                <>
                  <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> Saving…
                </>
              ) : (
                <>
                  <Plus className="h-4 w-4 mr-1.5" />
                  {editingName ? "Update var" : "Add var"}
                </>
              )}
            </Button>
            {editingName && (
              <Button variant="outline" onClick={handleCancelEdit} disabled={saving}>
                Cancel
              </Button>
            )}
          </div>
        </div>
      </SettingsSectionCard>

      <SettingsSectionCard
        title="Your env vars"
        description={
          hopxSynced
            ? "Synced to your Hopx sandbox as a .env file."
            : "Stored encrypted in the database."
        }
      >
        <div className="mb-3 flex items-center justify-end">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void load()}
            disabled={loading}
            className="h-7 text-xs"
          >
            <RefreshCw className={cn("h-3.5 w-3.5 mr-1", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
        {loading ? (
          <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : vars.length === 0 ? (
          <div className="rounded-xl border border-dashed border-foreground/15 p-8 text-center">
            <KeyRound className="mx-auto h-8 w-8 text-muted-foreground mb-3" />
            <p className="font-medium">No env vars set</p>
            <p className="text-sm text-muted-foreground mt-1 max-w-md mx-auto">
              Add your first env var above. The AI will be able to read it via
              the sandbox <code>.env</code> file when running code on your
              behalf.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {vars.map((v) => {
              const isRevealed = revealed[v.name];
              const display = v.is_secret
                ? isRevealed
                  ? v.value
                  : "•".repeat(Math.min(12, Math.max(8, (v.value || "").length || 8)))
                : v.value;
              return (
                <li key={v.name} className="flex items-start gap-3 py-3">
                  <KeyRound
                    className={cn(
                      "mt-0.5 h-4 w-4 shrink-0",
                      v.is_secret ? "text-amber-500" : "text-muted-foreground",
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="font-mono text-sm font-medium">{v.name}</p>
                      <span
                        className={cn(
                          "text-[10px] font-mono uppercase rounded px-1.5 py-0.5",
                          v.is_secret
                            ? "bg-amber-500/10 text-amber-700"
                            : "bg-foreground/5 text-muted-foreground",
                        )}
                      >
                        {v.is_secret ? "secret" : "plain"}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5 font-mono break-all">
                      {display}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {v.is_secret && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 w-7 p-0"
                        onClick={() =>
                          setRevealed((r) => ({ ...r, [v.name]: !r[v.name] }))
                        }
                        title={isRevealed ? "Hide" : "Reveal"}
                      >
                        {isRevealed ? (
                          <EyeOff className="h-3.5 w-3.5" />
                        ) : (
                          <Eye className="h-3.5 w-3.5" />
                        )}
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 w-7 p-0"
                      onClick={() => handleEdit(v)}
                      title="Edit"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                      onClick={() => handleDelete(v)}
                      title="Delete"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </SettingsSectionCard>
    </div>
  );
}
