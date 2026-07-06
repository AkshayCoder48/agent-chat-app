"use client";

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Wrench, Plus, Trash2, Pencil, Code, Search, Loader2 } from "lucide-react";
import { toast } from "sonner";

interface BuiltinTool {
  name: string;
  description: string;
}

interface ToolParameter {
  name: string;
  type: string;
  description: string;
  required: boolean;
}

interface CustomTool {
  id: string;
  name: string;
  description: string;
  parameters: ToolParameter[];
  code: string;
  created_by: "user" | "ai";
  is_enabled: boolean;
  created_at: string;
  updated_at: string | null;
}

interface CustomToolList {
  items: CustomTool[];
  total: number;
}

export default function ToolsSettingsPage() {
  const [builtinTools, setBuiltinTools] = useState<BuiltinTool[]>([]);
  const [customTools, setCustomTools] = useState<CustomTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<CustomTool | null>(null);
  const [viewing, setViewing] = useState<CustomTool | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [builtinRes, customRes] = await Promise.all([
        apiClient.get("/custom-tools/catalog"),
        apiClient.get("/custom-tools"),
      ]);
      const builtinData = (await builtinRes) as { tools: BuiltinTool[] };
      const customData = (await customRes) as CustomToolList;
      setBuiltinTools(builtinData.tools || []);
      setCustomTools(customData.items || []);
    } catch (e) {
      toast.error("Failed to load tools", {
        description: e instanceof Error ? e.message : "Unknown error",
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const filteredBuiltin = builtinTools.filter(
    (t) =>
      t.name.toLowerCase().includes(search.toLowerCase()) ||
      t.description.toLowerCase().includes(search.toLowerCase())
  );
  const filteredCustom = customTools.filter(
    (t) =>
      t.name.toLowerCase().includes(search.toLowerCase()) ||
      t.description.toLowerCase().includes(search.toLowerCase())
  );

  const handleToggle = async (tool: CustomTool, enabled: boolean) => {
    try {
      await apiClient.patch(`/custom-tools/${tool.id}`, { is_enabled: enabled });
      setCustomTools((prev) =>
        prev.map((t) => (t.id === tool.id ? { ...t, is_enabled: enabled } : t))
      );
    } catch (e) {
      toast.error("Failed to update tool", {
        description: e instanceof Error ? e.message : "Unknown error",
      });
    }
  };

  const handleDelete = async (tool: CustomTool) => {
    if (!confirm(`Delete tool "${tool.name}"? This cannot be undone.`)) return;
    try {
      await apiClient.delete(`/custom-tools/${tool.id}`);
      setCustomTools((prev) => prev.filter((t) => t.id !== tool.id));
      toast.success("Tool deleted", { description: tool.name });
    } catch (e) {
      toast.error("Failed to delete tool", {
        description: e instanceof Error ? e.message : "Unknown error",
      });
    }
  };

  const handleSaved = () => {
    setEditorOpen(false);
    setEditing(null);
    void fetchData();
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <Wrench className="h-6 w-6" />
          Tools
        </h1>
        <p className="text-muted-foreground mt-1">
          View built-in tools and create custom tools the AI can call.
        </p>
      </div>

      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search tools..."
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
          {/* Custom tools */}
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-medium">
                Custom tools{" "}
                <span className="text-muted-foreground text-sm">({customTools.length})</span>
              </h2>
            </div>
            {filteredCustom.length === 0 ? (
              <Card>
                <CardContent className="py-10 text-center text-muted-foreground">
                  No custom tools yet. Click "New tool" to create one — the AI will be
                  able to call it like any built-in tool.
                </CardContent>
              </Card>
            ) : (
              <div className="grid gap-3">
                {filteredCustom.map((tool) => (
                  <Card key={tool.id} className="animate-fade-in hover:shadow-md transition-shadow">
                    <CardHeader className="pb-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="space-y-1 flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <CardTitle className="text-base font-mono">{tool.name}</CardTitle>
                            <Badge variant={tool.created_by === "ai" ? "secondary" : "outline"}>
                              {tool.created_by === "ai" ? "AI-created" : "User-created"}
                            </Badge>
                            <Badge variant={tool.is_enabled ? "default" : "destructive"}>
                              {tool.is_enabled ? "Enabled" : "Disabled"}
                            </Badge>
                          </div>
                          <CardDescription className="text-xs">
                            {tool.description || "No description"}
                          </CardDescription>
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          <Switch
                            checked={tool.is_enabled}
                            onCheckedChange={(v) => handleToggle(tool, v)}
                          />
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setViewing(tool)}
                            title="View code"
                          >
                            <Code className="h-4 w-4" />
                          </Button>
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
                    </CardHeader>
                    <CardContent className="pt-0 text-xs text-muted-foreground">
                      <div>
                        <span className="font-medium">Parameters:</span>{" "}
                        {tool.parameters.length === 0
                          ? "none"
                          : tool.parameters
                              .map(
                                (p) =>
                                  `${p.name}: ${p.type}${p.required ? "" : "?"}`
                              )
                              .join(", ")}
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </section>

          {/* Built-in tools */}
          <section className="space-y-3">
            <h2 className="text-lg font-medium">
              Built-in tools{" "}
              <span className="text-muted-foreground text-sm">({builtinTools.length})</span>
            </h2>
            <div className="grid gap-2 md:grid-cols-2">
              {filteredBuiltin.map((tool) => (
                <Card key={tool.name} className="animate-fade-in hover:shadow-md transition-shadow">
                  <CardContent className="py-3 px-4">
                    <div className="font-mono text-sm font-medium">{tool.name}</div>
                    <div className="text-xs text-muted-foreground mt-1">
                      {tool.description}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </section>
        </>
      )}

      {/* Editor dialog */}
      <ToolEditor
        open={editorOpen}
        tool={editing}
        onClose={() => {
          setEditorOpen(false);
          setEditing(null);
        }}
        onSaved={handleSaved}
      />

      {/* Code viewer dialog */}
      <Dialog open={!!viewing} onOpenChange={(v) => !v && setViewing(null)}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="font-mono">{viewing?.name}</DialogTitle>
            <DialogDescription>{viewing?.description}</DialogDescription>
          </DialogHeader>
          <div className="flex-1 overflow-auto">
            <pre className="text-xs bg-muted p-4 rounded-md font-mono whitespace-pre-wrap break-words">
              {viewing?.code}
            </pre>
          </div>
          {viewing && viewing.parameters.length > 0 && (
            <div className="border-t pt-3 space-y-1">
              <div className="text-xs font-medium">Parameters:</div>
              {viewing.parameters.map((p) => (
                <div key={p.name} className="text-xs font-mono">
                  <span className="font-semibold">{p.name}</span>
                  <span className="text-muted-foreground">: {p.type}</span>
                  {p.required ? (
                    <span className="text-destructive ml-1">(required)</span>
                  ) : (
                    <span className="text-muted-foreground ml-1">(optional)</span>
                  )}
                  {p.description && (
                    <span className="text-muted-foreground ml-2">— {p.description}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
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
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [params, setParams] = useState<ToolParameter[]>([]);
  const [code, setCode] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (tool) {
      setName(tool.name);
      setDescription(tool.description);
      setParams(tool.parameters);
      setCode(tool.code);
    } else {
      setName("");
      setDescription("");
      setParams([]);
      setCode('def run():\n    return "Hello from custom tool!"\n');
    }
  }, [tool, open]);

  const addParam = () => {
    setParams([
      ...params,
      { name: `param${params.length + 1}`, type: "string", description: "", required: true },
    ]);
  };

  const updateParam = (idx: number, field: keyof ToolParameter, value: string | boolean) => {
    setParams(params.map((p, i) => (i === idx ? { ...p, [field]: value } : p)));
  };

  const removeParam = (idx: number) => {
    setParams(params.filter((_, i) => i !== idx));
  };

  const handleSave = async () => {
    if (!name.trim() || !code.trim()) {
      toast.error("Missing fields", { description: "Name and code are required." });
      return;
    }
    setSaving(true);
    try {
      const body = {
        name,
        description,
        parameters: params,
        code,
        is_enabled: true,
      };
      if (tool) {
        await apiClient.patch(`/custom-tools/${tool.id}`, body);
        toast.success("Tool updated", { description: name });
      } else {
        await apiClient.post("/custom-tools", body);
        toast.success("Tool created", { description: name });
      }
      onSaved();
    } catch (e) {
      toast.error("Failed to save tool", {
        description: e instanceof Error ? e.message : "Unknown error",
      });
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
            Define a Python function called <code className="font-mono">run</code> that
            takes your parameters as keyword arguments. The AI will be able to call this
            tool by name in any chat.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-auto space-y-4 py-2">
          <div className="grid gap-2">
            <Label htmlFor="tool-name">Tool name (snake_case)</Label>
            <Input
              id="tool-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my_custom_tool"
              className="font-mono"
              disabled={!!tool}
            />
            <p className="text-xs text-muted-foreground">
              Lowercase letters, digits, underscores. Cannot be renamed after creation.
            </p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="tool-desc">Description</Label>
            <Textarea
              id="tool-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this tool do? When should the AI call it?"
              rows={2}
            />
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label>Parameters</Label>
              <Button size="sm" variant="outline" onClick={addParam}>
                <Plus className="h-3 w-3 mr-1" />
                Add parameter
              </Button>
            </div>
            {params.length === 0 ? (
              <p className="text-xs text-muted-foreground">No parameters.</p>
            ) : (
              <div className="space-y-2">
                {params.map((p, idx) => (
                  <div key={idx} className="grid grid-cols-12 gap-2 items-start">
                    <Input
                      className="col-span-3 font-mono text-xs"
                      placeholder="name"
                      value={p.name}
                      onChange={(e) => updateParam(idx, "name", e.target.value)}
                    />
                    <select
                      className="col-span-2 h-9 rounded-md border border-input bg-background px-2 text-xs"
                      value={p.type}
                      onChange={(e) => updateParam(idx, "type", e.target.value)}
                    >
                      <option value="string">string</option>
                      <option value="integer">integer</option>
                      <option value="number">number</option>
                      <option value="boolean">boolean</option>
                      <option value="array">array</option>
                      <option value="object">object</option>
                    </select>
                    <Input
                      className="col-span-4 text-xs"
                      placeholder="description"
                      value={p.description}
                      onChange={(e) => updateParam(idx, "description", e.target.value)}
                    />
                    <label className="col-span-2 flex items-center gap-1 text-xs">
                      <Switch
                        checked={p.required}
                        onCheckedChange={(v) => updateParam(idx, "required", v)}
                      />
                      required
                    </label>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="col-span-1 text-destructive"
                      onClick={() => removeParam(idx)}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="grid gap-2">
            <Label htmlFor="tool-code">Python code (must define `run`)</Label>
            <Textarea
              id="tool-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="font-mono text-xs"
              rows={12}
              spellCheck={false}
            />
            <p className="text-xs text-muted-foreground">
              The function can be sync or async. It receives your parameters as keyword
              args and should return a string, dict, or list.
            </p>
          </div>
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
