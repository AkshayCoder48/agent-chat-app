"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  Download,
  Loader2,
  Package,
  Plus,
  Trash2,
  Upload,
  Wrench,
} from "lucide-react";
import { toast } from "sonner";

import { Button, Input } from "@/components/ui";
import { SectionCard as SettingsSectionCard } from "@/components/settings/settings-section";
import { cn } from "@/lib/utils";

interface InstalledSkill {
  name: string;
  description?: string;
  path: string;
}

interface CatalogSkill {
  name: string;
  description?: string;
  downloads?: number;
  url?: string;
  installed: boolean;
}

interface CatalogResponse {
  skills: CatalogSkill[];
  source: string;
}

interface InstalledResponse {
  skills: InstalledSkill[];
}

export default function SkillsSettingsPage() {
  const [installed, setInstalled] = useState<InstalledSkill[]>([]);
  const [catalog, setCatalog] = useState<CatalogSkill[]>([]);
  const [loadingInstalled, setLoadingInstalled] = useState(true);
  const [loadingCatalog, setLoadingCatalog] = useState(true);
  const [installing, setInstalling] = useState<string | null>(null);
  const [uninstalling, setUninstalling] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadInstalled = useCallback(async () => {
    setLoadingInstalled(true);
    try {
      const res = await fetch("/api/skills/installed");
      if (!res.ok) throw new Error("Failed to load installed skills");
      const data = (await res.json()) as InstalledResponse;
      setInstalled(data.skills ?? []);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load installed skills");
    } finally {
      setLoadingInstalled(false);
    }
  }, []);

  const loadCatalog = useCallback(async () => {
    setLoadingCatalog(true);
    try {
      const res = await fetch("/api/skills/catalog");
      if (!res.ok) throw new Error("Failed to load skill catalog");
      const data = (await res.json()) as CatalogResponse;
      setCatalog(data.skills ?? []);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load skill catalog");
    } finally {
      setLoadingCatalog(false);
    }
  }, []);

  useEffect(() => {
    void loadInstalled();
    void loadCatalog();
  }, [loadInstalled, loadCatalog]);

  const installSkill = async (name: string) => {
    setInstalling(name);
    try {
      const res = await fetch(`/api/skills/install/${encodeURIComponent(name)}`, {
        method: "POST",
      });
      if (!res.ok) {
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(err.detail ?? `Failed to install ${name}`);
      }
      toast.success(`Installed skill: ${name}`);
      await loadInstalled();
      // Mark as installed in the catalog view too.
      setCatalog((cs) => cs.map((c) => (c.name === name ? { ...c, installed: true } : c)));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Install failed");
    } finally {
      setInstalling(null);
    }
  };

  const uninstallSkill = async (name: string) => {
    setUninstalling(name);
    try {
      const res = await fetch(`/api/skills/${encodeURIComponent(name)}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to uninstall skill");
      toast.success(`Removed skill: ${name}`);
      await loadInstalled();
      setCatalog((cs) => cs.map((c) => (c.name === name ? { ...c, installed: false } : c)));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Uninstall failed");
    } finally {
      setUninstalling(null);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/skills/upload", { method: "POST", body: fd });
      if (!res.ok) {
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(err.detail ?? "Upload failed");
      }
      const data = (await res.json()) as { name: string };
      toast.success(`Uploaded skill: ${data.name}`);
      await loadInstalled();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <div className="space-y-6">
      <SettingsSectionCard
        title="Installed skills"
        description="Skills are contextual capabilities the AI uses automatically when your task matches. Install from the catalog below or upload a SKILL.md / .zip file."
      >
        {loadingInstalled ? (
          <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : installed.length === 0 ? (
          <div className="rounded-xl border border-dashed border-foreground/15 p-8 text-center">
            <Wrench className="mx-auto h-8 w-8 text-muted-foreground mb-3" />
            <p className="font-medium">No skills installed yet</p>
            <p className="text-sm text-muted-foreground mt-1 max-w-md mx-auto">
              Browse the ClawHub catalog below and click <em>Install</em>, or
              upload a SKILL.md / .zip file from the section below.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {installed.map((s) => (
              <li key={s.path} className="flex items-start gap-3 py-3">
                <Package className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-sm">{s.name}</p>
                  {s.description ? (
                    <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                      {s.description}
                    </p>
                  ) : null}
                  <p className="text-[10px] font-mono text-muted-foreground/60 mt-1">
                    {s.path}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={uninstalling === s.name}
                  onClick={() => uninstallSkill(s.name)}
                  className="h-7 text-xs text-muted-foreground hover:text-destructive"
                >
                  {uninstalling === s.name ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5" />
                  )}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </SettingsSectionCard>

      <SettingsSectionCard
        title="Upload a skill"
        description="Upload a SKILL.md file or a .zip archive. The skill will be extracted and made available to the AI on the next chat turn."
      >
        <div className="rounded-xl border border-dashed border-foreground/15 p-8 text-center">
          <input
            ref={fileInputRef}
            type="file"
            accept=".zip,.md"
            onChange={handleUpload}
            disabled={uploading}
            className="hidden"
            id="skill-upload-input"
          />
          <Upload className="mx-auto h-8 w-8 text-muted-foreground mb-3" />
          <p className="font-medium">
            {uploading ? "Uploading…" : "Drop a .zip or SKILL.md here"}
          </p>
          <p className="text-sm text-muted-foreground mt-1 max-w-md mx-auto">
            The .zip may either contain SKILL.md at its root or a single
            top-level folder containing SKILL.md.
          </p>
          <Button
            size="sm"
            variant="outline"
            className="mt-3"
            disabled={uploading}
            onClick={() => fileInputRef.current?.click()}
          >
            {uploading ? (
              <>
                <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> Uploading…
              </>
            ) : (
              <>
                <Plus className="h-4 w-4 mr-1.5" /> Choose file
              </>
            )}
          </Button>
        </div>
      </SettingsSectionCard>

      <SettingsSectionCard
        title="ClawHub catalog"
        description="Browse community skills sorted by download count. Click Install to add them to your workspace."
      >
        {loadingCatalog ? (
          <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading catalog…
          </div>
        ) : catalog.length === 0 ? (
          <div className="rounded-xl border border-dashed border-foreground/15 p-8 text-center">
            <Package className="mx-auto h-8 w-8 text-muted-foreground mb-3" />
            <p className="font-medium">Catalog unavailable</p>
            <p className="text-sm text-muted-foreground mt-1">
              The ClawHub API is unreachable right now. Try uploading a skill
              directly instead.
            </p>
          </div>
        ) : (
          <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {catalog.map((c) => {
              const isInstalling = installing === c.name;
              return (
                <li
                  key={c.name}
                  className={cn(
                    "flex flex-col gap-2 rounded-xl border border-border p-3 transition-colors",
                    c.installed && "bg-emerald-500/5 border-emerald-500/30",
                  )}
                >
                  <div className="flex items-start gap-2">
                    <Package className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
                    <div className="min-w-0 flex-1">
                      <p className="font-mono text-sm font-medium">{c.name}</p>
                      {c.description ? (
                        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                          {c.description}
                        </p>
                      ) : null}
                    </div>
                    {c.installed && (
                      <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
                    )}
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-mono text-muted-foreground/60">
                      {c.downloads ? `${c.downloads} downloads` : "—"}
                    </span>
                    {c.installed ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 text-xs"
                        onClick={() => uninstallSkill(c.name)}
                        disabled={uninstalling === c.name}
                      >
                        {uninstalling === c.name ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <>
                            <Trash2 className="h-3.5 w-3.5 mr-1" /> Remove
                          </>
                        )}
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs"
                        onClick={() => installSkill(c.name)}
                        disabled={isInstalling}
                      >
                        {isInstalling ? (
                          <>
                            <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> Installing…
                          </>
                        ) : (
                          <>
                            <Download className="h-3.5 w-3.5 mr-1" /> Install
                          </>
                        )}
                      </Button>
                    )}
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
