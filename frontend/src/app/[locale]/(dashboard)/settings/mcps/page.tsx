"use client";

import { useCallback, useEffect, useState } from "react";
import { Blocks, Loader2, Plus, Power, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button, Input, Label } from "@/components/ui";
import { SectionCard as SettingsSectionCard } from "@/components/settings/settings-section";
import { cn } from "@/lib/utils";

interface MCPServer {
  id: string;
  name: string;
  transport: string;
  command?: string | null;
  args: string[];
  env: Record<string, string>;
  url?: string | null;
  headers: Record<string, string>;
  is_active: boolean;
}

const EMPTY_FORM = {
  name: "",
  transport: "stdio" as "stdio" | "sse" | "streamable_http",
  command: "",
  args: "",
  env: "",
  url: "",
  headers: "",
};

export default function McpsSettingsPage() {
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ ...EMPTY_FORM });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/mcp-servers");
      if (!res.ok) throw new Error("Failed to load MCP servers");
      const data = (await res.json()) as MCPServer[];
      setServers(data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleAdd = async () => {
    if (!form.name.trim()) {
      toast.error("Name is required");
      return;
    }
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        name: form.name.trim(),
        transport: form.transport,
        is_active: true,
      };
      if (form.transport === "stdio") {
        payload.command = form.command.trim();
        payload.args = form.args
          .split(/\s+/)
          .map((s) => s.trim())
          .filter(Boolean);
        try {
          payload.env = form.env.trim() ? JSON.parse(form.env) : {};
        } catch {
          throw new Error("env must be a JSON object");
        }
      } else {
        payload.url = form.url.trim();
        try {
          payload.headers = form.headers.trim() ? JSON.parse(form.headers) : {};
        } catch {
          throw new Error("headers must be a JSON object");
        }
      }

      const res = await fetch("/api/mcp-servers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(err.detail ?? "Failed to add MCP server");
      }
      toast.success(`Added MCP server: ${form.name}`);
      setForm({ ...EMPTY_FORM });
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Add failed");
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (s: MCPServer) => {
    try {
      const res = await fetch(`/api/mcp-servers/${s.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !s.is_active }),
      });
      if (!res.ok) throw new Error("Failed to toggle");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Toggle failed");
    }
  };

  const handleDelete = async (s: MCPServer) => {
    if (!confirm(`Delete MCP server ${s.name}?`)) return;
    try {
      const res = await fetch(`/api/mcp-servers/${s.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete");
      toast.success(`Removed ${s.name}`);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed");
    }
  };

  return (
    <div className="space-y-6">
      <SettingsSectionCard
        title="MCP servers"
        description="Model Context Protocol (MCP) servers expose tools and data sources to the AI. Add a stdio / SSE / streamable-HTTP server below — the AI picks up its tools on the next chat turn."
      >
        {loading ? (
          <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : servers.length === 0 ? (
          <div className="rounded-xl border border-dashed border-foreground/15 p-8 text-center">
            <Blocks className="mx-auto h-8 w-8 text-muted-foreground mb-3" />
            <p className="font-medium">No MCP servers connected</p>
            <p className="text-sm text-muted-foreground mt-1 max-w-md mx-auto">
              Add a server using the form below. Common choices: filesystem
              (stdio), GitHub (stdio), Slack (SSE), Zapier (streamable-http).
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {servers.map((s) => (
              <li key={s.id} className="flex items-start gap-3 py-3">
                <Blocks
                  className={cn(
                    "mt-0.5 h-4 w-4 shrink-0",
                    s.is_active ? "text-brand" : "text-muted-foreground",
                  )}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="font-medium text-sm">{s.name}</p>
                    <span className="text-[10px] font-mono uppercase rounded bg-foreground/5 px-1.5 py-0.5">
                      {s.transport}
                    </span>
                    {!s.is_active && (
                      <span className="text-[10px] font-mono uppercase text-amber-600">disabled</span>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                    {s.transport === "stdio"
                      ? `${s.command ?? ""} ${(s.args ?? []).join(" ")}`
                      : s.url ?? ""}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 text-xs"
                  onClick={() => toggleActive(s)}
                  title={s.is_active ? "Disable" : "Enable"}
                >
                  <Power className={cn("h-3.5 w-3.5", s.is_active && "text-emerald-500")} />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 text-xs text-muted-foreground hover:text-destructive"
                  onClick={() => handleDelete(s)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </SettingsSectionCard>

      <SettingsSectionCard
        title="Add an MCP server"
        description="Configure a new MCP server. Pick the transport, then fill in the corresponding fields."
      >
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="mcp-name" className="text-xs uppercase">Name</Label>
              <Input
                id="mcp-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. filesystem"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="mcp-transport" className="text-xs uppercase">Transport</Label>
              <select
                id="mcp-transport"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={form.transport}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    transport: e.target.value as typeof form.transport,
                  }))
                }
              >
                <option value="stdio">stdio</option>
                <option value="sse">sse</option>
                <option value="streamable_http">streamable_http</option>
              </select>
            </div>
          </div>

          {form.transport === "stdio" ? (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="mcp-command" className="text-xs uppercase">Command</Label>
                <Input
                  id="mcp-command"
                  value={form.command}
                  onChange={(e) => setForm((f) => ({ ...f, command: e.target.value }))}
                  placeholder="e.g. npx"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="mcp-args" className="text-xs uppercase">Args (space-separated)</Label>
                <Input
                  id="mcp-args"
                  value={form.args}
                  onChange={(e) => setForm((f) => ({ ...f, args: e.target.value }))}
                  placeholder="e.g. -y @modelcontextprotocol/server-filesystem /tmp"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="mcp-env" className="text-xs uppercase">Env (JSON)</Label>
                <Input
                  id="mcp-env"
                  value={form.env}
                  onChange={(e) => setForm((f) => ({ ...f, env: e.target.value }))}
                  placeholder='e.g. {"API_KEY":"…"}'
                  className="font-mono text-xs"
                />
              </div>
            </>
          ) : (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="mcp-url" className="text-xs uppercase">URL</Label>
                <Input
                  id="mcp-url"
                  value={form.url}
                  onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
                  placeholder="https://example.com/mcp"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="mcp-headers" className="text-xs uppercase">Headers (JSON)</Label>
                <Input
                  id="mcp-headers"
                  value={form.headers}
                  onChange={(e) => setForm((f) => ({ ...f, headers: e.target.value }))}
                  placeholder='{"Authorization":"Bearer …"}'
                  className="font-mono text-xs"
                />
              </div>
            </>
          )}

          <Button onClick={handleAdd} disabled={saving}>
            {saving ? (
              <>
                <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> Saving…
              </>
            ) : (
              <>
                <Plus className="h-4 w-4 mr-1.5" /> Add server
              </>
            )}
          </Button>
        </div>
      </SettingsSectionCard>
    </div>
  );
}
