"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Code,
  Download,
  Loader2,
  Pencil,
  Plus,
  Power,
  Search,
  Trash2,
  Wrench,
} from "lucide-react";
import { toast } from "sonner";

import {
  Button,
  Input,
  Label,
  Switch,
  Textarea,
} from "@/components/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionCard as SettingsSectionCard } from "@/components/settings/settings-section";
import { cn } from "@/lib/utils";

interface CustomTool {
  id: string;
  name: string;
  description: string;
  parameters_schema: Record<string, unknown>;
  impl_kind: "http_webhook" | "python_snippet";
  http_url?: string | null;
  http_headers: Record<string, string>;
  python_source?: string | null;
  is_active: boolean;
}

interface CatalogItem {
  name: string;
  description: string;
  parameters_schema: Record<string, unknown>;
  impl_kind: "http_webhook" | "python_snippet";
  http_url?: string | null;
  http_headers: Record<string, string>;
  python_source?: string | null;
  installed: boolean;
}

const EMPTY_FORM = {
  name: "",
  description: "",
  impl_kind: "python_snippet" as "http_webhook" | "python_snippet",
  http_url: "",
  http_headers: "{}",
  python_source: "return {'hello': 'world'}",
  parameters_schema: '{"type":"object","properties":{}}',
};

export default function ToolsSettingsPage() {
  const [tools, setTools] = useState<CustomTool[]>([]);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<CustomTool | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [customRes, catalogRes] = await Promise.all([
        fetch("/api/custom-tools"),
        fetch("/api/custom-tools/catalog"),
      ]);
      if (!customRes.ok) throw new Error("Failed to load custom tools");
      const customData = (await customRes.json()) as CustomTool[];
      setTools(customData);
      if (catalogRes.ok) {
        const catalogData = (await catalogRes.json()) as CatalogItem[];
        setCatalog(catalogData);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const filtered = tools.filter(
    (t) =>
      t.name.toLowerCase().includes(search.toLowerCase()) ||
      t.description.toLowerCase().includes(search.toLowerCase()),
  );

  const handleToggle = async (tool: CustomTool, active: boolean) => {
    try {
      const res = await fetch(`/api/custom-tools/${tool.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: active }),
      });
      if (!res.ok) throw new Error("Failed to toggle");
      setTools((prev) =>
        prev.map((t) => (t.id === tool.id ? { ...t, is_active: active } : t)),
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Toggle failed");
    }
  };

  const handleDelete = async (tool: CustomTool) => {
    if (!confirm(`Delete tool "${tool.name}"?`)) return;
    try {
      const res = await fetch(`/api/custom-tools/${tool.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete");
      toast.success("Tool deleted", { description: tool.name });
      await fetchData();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Delete failed");
    }
  };

  const installCatalog = async (item: CatalogItem) => {
    try {
      const res = await fetch("/api/custom-tools", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: item.name,
          description: item.description,
          parameters_schema: item.parameters_schema,
          impl_kind: item.impl_kind,
          http_url: item.http_url,
          http_headers: item.http_headers,
          python_source: item.python_source,
          is_active: true,
        }),
      });
      if (!res.ok) {
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(err.detail ?? "Install failed");
      }
      toast.success(`Installed: ${item.name}`);
      await fetchData();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Install failed");
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <Wrench className="h-6 w-6" />
          Custom tools
        </h1>
        <p className="text-muted-foreground mt-1">
          Custom tools are functions the AI can call. Define them as HTTP
          webhooks or Python snippets — the AI picks them up automatically on
          the next chat turn.
        </p>
      </div>

      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search tools…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Button
          onClick={() => {
            setEditing(null);
            setEditorOpen(true);
          }}
        >
          <Plus className="h-4 w-4 mr-2" />
          New tool
        </Button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          <SettingsSectionCard
            title="Your tools"
            description="Tools you've created or installed from the catalog below."
          >
            {filtered.length === 0 ? (
              <div className="rounded-xl border border-dashed border-foreground/15 p-8 text-center">
                <Wrench className="mx-auto h-8 w-8 text-muted-foreground mb-3" />
                <p className="font-medium">No custom tools yet</p>
                <p className="text-sm text-muted-foreground mt-1 max-w-md mx-auto">
                  Click <em>New tool</em> above, or install one from the
                  starter catalog below.
                </p>
              </div>
            ) : (
              <div className="grid gap-3">
                {filtered.map((tool) => (
                  <Card key={tool.id} className="animate-fade-in hover:shadow-md transition-shadow">
                    <CardContent className="py-3 px-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1 space-y-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-mono text-sm font-medium">
                              {tool.name}
                            </span>
                            <Badge variant="outline" className="text-[10px]">
                              {tool.impl_kind === "http_webhook" ? "HTTP" : "Python"}
                            </Badge>
                            <Badge variant={tool.is_active ? "default" : "secondary"}>
                              {tool.is_active ? "Enabled" : "Disabled"}
                            </Badge>
                          </div>
                          <p className="text-xs text-muted-foreground">
                            {tool.description || "No description"}
                          </p>
                          {tool.impl_kind === "http_webhook" && tool.http_url && (
                            <p className="text-[10px] font-mono text-muted-foreground/60 truncate">
                              POST {tool.http_url}
                            </p>
                          )}
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          <Switch
                            checked={tool.is_active}
                            onCheckedChange={(v) => handleToggle(tool, v)}
                          />
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              setEditing(tool);
                              setEditorOpen(true);
                            }}
                            title="Edit"
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleDelete(tool)}
                            title="Delete"
                            className="text-destructive hover:text-destructive"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </SettingsSectionCard>

          <SettingsSectionCard
            title="Starter catalog"
            description="One-click install these starter tools. They cover common patterns (HTTP webhook, Python snippet) you can copy and modify."
          >
            <ul className="grid gap-3 sm:grid-cols-2">
              {catalog.map((c) => (
                <li
                  key={c.name}
                  className={cn(
                    "flex flex-col gap-2 rounded-xl border border-border p-3",
                    c.installed && "bg-emerald-500/5 border-emerald-500/30",
                  )}
                >
                  <div className="flex items-start gap-2">
                    <Code className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
                    <div className="min-w-0 flex-1">
                      <p className="font-mono text-sm font-medium">{c.name}</p>
                      <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                        {c.description}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-mono uppercase text-muted-foreground/60">
                      {c.impl_kind === "http_webhook" ? "HTTP" : "Python"}
                    </span>
                    {c.installed ? (
                      <Badge variant="outline" className="text-[10px]">
                        Installed
                      </Badge>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs"
                        onClick={() => installCatalog(c)}
                      >
                        <Download className="h-3.5 w-3.5 mr-1" /> Install
                      </Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </SettingsSectionCard>
        </>
      )}

      <ToolEditor
        open={editorOpen}
        tool={editing}
        onClose={() => {
          setEditorOpen(false);
          setEditing(null);
        }}
        onSaved={() => {
          setEditorOpen(false);
          setEditing(null);
          void fetchData();
        }}
      />
    </div>
  );
}

/* -------------------- Tool editor -------------------- */

interface ToolEditorProps {
  open: boolean;
  tool: CustomTool | null;
  onClose: () => void;
  onSaved: () => void;
}

function ToolEditor({ open, tool, onClose, onSaved }: ToolEditorProps) {
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (tool) {
      setForm({
        name: tool.name,
        description: tool.description,
        impl_kind: tool.impl_kind,
        http_url: tool.http_url ?? "",
        http_headers: JSON.stringify(tool.http_headers ?? {}, null, 2),
        python_source: tool.python_source ?? "return {'hello': 'world'}",
        parameters_schema: JSON.stringify(tool.parameters_schema ?? {}, null, 2),
      });
    } else {
      setForm({ ...EMPTY_FORM });
    }
  }, [tool, open]);

  const handleSave = async () => {
    if (!form.name.trim()) {
      toast.error("Name is required");
      return;
    }
    let parsedHeaders: Record<string, string> = {};
    let parsedSchema: Record<string, unknown> = {};
    try {
      parsedHeaders = form.http_headers.trim() ? JSON.parse(form.http_headers) : {};
    } catch {
      toast.error("HTTP headers must be a JSON object");
      return;
    }
    try {
      parsedSchema = form.parameters_schema.trim()
        ? JSON.parse(form.parameters_schema)
        : {};
    } catch {
      toast.error("Parameters schema must be a JSON object");
      return;
    }
    if (form.impl_kind === "http_webhook" && !form.http_url.trim()) {
      toast.error("HTTP webhook requires a URL");
      return;
    }
    if (form.impl_kind === "python_snippet" && !form.python_source.trim()) {
      toast.error("Python snippet requires source code");
      return;
    }

    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        description: form.description.trim() || "Custom tool",
        parameters_schema: parsedSchema,
        impl_kind: form.impl_kind,
        http_url: form.impl_kind === "http_webhook" ? form.http_url.trim() : null,
        http_headers: parsedHeaders,
        python_source: form.impl_kind === "python_snippet" ? form.python_source : null,
        is_active: true,
      };
      const url = tool ? `/api/custom-tools/${tool.id}` : "/api/custom-tools";
      const method = tool ? "PUT" : "POST";
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(err.detail ?? "Save failed");
      }
      toast.success(tool ? "Tool updated" : "Tool created", { description: form.name });
      onSaved();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>{tool ? "Edit tool" : "Create custom tool"}</DialogTitle>
          <DialogDescription>
            Define a tool the AI can call. Choose HTTP webhook (POST args to a
            URL) or Python snippet (run in a sandbox).
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-auto space-y-4 py-2">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="tool-name" className="text-xs uppercase">Name (snake_case)</Label>
              <Input
                id="tool-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="my_custom_tool"
                className="font-mono"
                disabled={!!tool}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tool-kind" className="text-xs uppercase">Implementation</Label>
              <select
                id="tool-kind"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={form.impl_kind}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    impl_kind: e.target.value as "http_webhook" | "python_snippet",
                  }))
                }
              >
                <option value="python_snippet">Python snippet (sandboxed)</option>
                <option value="http_webhook">HTTP webhook (POST)</option>
              </select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="tool-desc" className="text-xs uppercase">Description</Label>
            <Textarea
              id="tool-desc"
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              placeholder="What does this tool do? When should the AI call it?"
              rows={2}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="tool-schema" className="text-xs uppercase">
              Parameters JSON Schema
            </Label>
            <Textarea
              id="tool-schema"
              value={form.parameters_schema}
              onChange={(e) => setForm((f) => ({ ...f, parameters_schema: e.target.value }))}
              className="font-mono text-xs"
              rows={4}
              spellCheck={false}
            />
          </div>

          {form.impl_kind === "http_webhook" ? (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="tool-url" className="text-xs uppercase">HTTP URL</Label>
                <Input
                  id="tool-url"
                  value={form.http_url}
                  onChange={(e) => setForm((f) => ({ ...f, http_url: e.target.value }))}
                  placeholder="https://example.com/webhook"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tool-headers" className="text-xs uppercase">Headers (JSON)</Label>
                <Textarea
                  id="tool-headers"
                  value={form.http_headers}
                  onChange={(e) => setForm((f) => ({ ...f, http_headers: e.target.value }))}
                  className="font-mono text-xs"
                  rows={3}
                  spellCheck={false}
                />
              </div>
            </>
          ) : (
            <div className="space-y-1.5">
              <Label htmlFor="tool-src" className="text-xs uppercase">Python source</Label>
              <Textarea
                id="tool-src"
                value={form.python_source}
                onChange={(e) => setForm((f) => ({ ...f, python_source: e.target.value }))}
                className="font-mono text-xs"
                rows={10}
                spellCheck={false}
              />
              <p className="text-xs text-muted-foreground">
                The snippet runs in a restricted Python sandbox (no imports
                beyond math/json/datetime/re). The kwargs are available as a
                dict named <code>_args</code>. Use <code>return</code> to
                return a value.
              </p>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            {tool ? "Save changes" : "Create tool"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
