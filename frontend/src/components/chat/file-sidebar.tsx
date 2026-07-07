"use client";

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Folder,
  File as FileIcon,
  Download,
  FolderDown,
  RefreshCw,
  ChevronRight,
  Home,
  Loader2,
  Search,
  Upload,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface WorkspaceEntry {
  name: string;
  type: "file" | "dir";
  size: number;
}

interface WorkspaceListing {
  path: string;
  absolute: string;
  parent: string | null;
  entries: WorkspaceEntry[];
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileExtension(name: string): string {
  const idx = name.lastIndexOf(".");
  return idx > 0 ? name.slice(idx + 1).toLowerCase() : "";
}

const EXT_ICONS: Record<string, string> = {
  md: "📝",
  txt: "📄",
  py: "🐍",
  js: "📜",
  ts: "📜",
  tsx: "⚛️",
  jsx: "⚛️",
  json: "⚙️",
  html: "🌐",
  css: "🎨",
  csv: "📊",
  png: "🖼️",
  jpg: "🖼️",
  jpeg: "🖼️",
  gif: "🖼️",
  svg: "🖼️",
  pdf: "📕",
  doc: "📘",
  docx: "📘",
  xls: "📗",
  xlsx: "📗",
  zip: "📦",
};

export function FileSidebar({ onRefreshKey }: { onRefreshKey?: string }) {
  const [listing, setListing] = useState<WorkspaceListing | null>(null);
  const [currentPath, setCurrentPath] = useState(".");
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  // Bump on every "workspace might have changed" signal so the listing
  // re-fetches. Driven by both the parent's `onRefreshKey` prop and the
  // local WS-listener below.
  const [refreshTick, setRefreshTick] = useState(0);

  const fetchListing = useCallback(
    async (path: string) => {
      setLoading(true);
      try {
        const data = (await apiClient.get(
          `/workspace/files?path=${encodeURIComponent(path)}`
        )) as WorkspaceListing;
        setListing(data);
      } catch (e) {
        toast.error("Failed to load files", {
          description: e instanceof Error ? e.message : "Unknown error",
        });
        setListing(null);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  // Auto-refresh when the agent completes a workspace-mutating tool call
  // (create_file / write_file / delete_file / run_terminal / etc.). The
  // chat-container's WS hook fires a window event for every tool_result;
  // we filter here to the names that actually change the workspace.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ tool_name: string }>).detail;
      const name = detail?.tool_name ?? "";
      if (
        [
          "create_file", "write_file", "edit_file", "delete_file",
          "create_folder", "delete_folder", "run_terminal", "send_file",
          "send_folder", "upload",
        ].includes(name)
      ) {
        setRefreshTick((t) => t + 1);
      }
    };
    window.addEventListener("tool_result", handler as EventListener);
    return () => window.removeEventListener("tool_result", handler as EventListener);
  }, []);

  useEffect(() => {
    void fetchListing(currentPath);
  }, [currentPath, fetchListing, onRefreshKey, refreshTick]);

  const navigateTo = (path: string) => {
    setCurrentPath(path);
    setSearch("");
  };

  const handleDownloadFile = async (entry: WorkspaceEntry) => {
    if (entry.type !== "file") return;
    const fullPath = currentPath === "." ? entry.name : `${currentPath}/${entry.name}`;
    try {
      const resp = await fetch(
        `/api/workspace/files/download?path=${encodeURIComponent(fullPath)}`
      );
      if (!resp.ok) throw new Error(`Download failed: ${resp.status}`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = entry.name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error("Download failed", {
        description: e instanceof Error ? e.message : "Unknown error",
      });
    }
  };

  const handleDownloadFolder = async (entry: WorkspaceEntry) => {
    if (entry.type !== "dir") return;
    const fullPath = currentPath === "." ? entry.name : `${currentPath}/${entry.name}`;
    try {
      const resp = await fetch(
        `/api/workspace/files/download-folder?path=${encodeURIComponent(fullPath)}`
      );
      if (!resp.ok) throw new Error(`Download failed: ${resp.status}`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${entry.name}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error("Folder download failed", {
        description: e instanceof Error ? e.message : "Unknown error",
      });
    }
  };

  const entries = listing?.entries || [];
  const filtered = search
    ? entries.filter((e) => e.name.toLowerCase().includes(search.toLowerCase()))
    : entries;
  const dirs = filtered.filter((e) => e.type === "dir");
  const files = filtered.filter((e) => e.type === "file");

  return (
    <div className="flex h-full flex-col bg-card border-l border-border">
      {/* Header */}
      <div className="border-b border-border px-3 py-3 space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold flex items-center gap-1.5">
            <Folder className="h-4 w-4" />
            Files
          </h3>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => fetchListing(currentPath)}
            disabled={loading}
            className="h-7 w-7 p-0"
            title="Refresh"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          </Button>
        </div>
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
          <Input
            placeholder="Search files..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-7 pl-7 text-xs"
          />
        </div>
        {/* Breadcrumb */}
        <div className="flex items-center gap-1 text-xs text-muted-foreground overflow-x-auto scrollbar-thin">
          <button
            onClick={() => navigateTo(".")}
            className="hover:text-foreground transition-colors shrink-0"
          >
            <Home className="h-3 w-3" />
          </button>
          {currentPath !== "." &&
            currentPath
              .split("/")
              .filter(Boolean)
              .map((part, idx, arr) => {
                const path = arr.slice(0, idx + 1).join("/");
                return (
                  <span key={path} className="flex items-center gap-1 shrink-0">
                    <ChevronRight className="h-3 w-3" />
                    <button
                      onClick={() => navigateTo(path)}
                      className="hover:text-foreground transition-colors"
                    >
                      {part}
                    </button>
                  </span>
                );
              })}
        </div>
      </div>

      {/* File list */}
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading && !listing ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : !listing ? (
          <div className="text-center py-8 text-sm text-muted-foreground px-4">
            No workspace files. Ask the AI to create a file.
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-8 text-sm text-muted-foreground px-4">
            {search ? "No matching files." : "This folder is empty."}
          </div>
        ) : (
          <ul className="py-1 animate-fade-in">
            {/* Parent dir link */}
            {listing.parent && (
              <li>
                <button
                  onClick={() => navigateTo(listing.parent!)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-xs hover:bg-foreground/5 transition-colors"
                >
                  <Folder className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="text-muted-foreground">..</span>
                </button>
              </li>
            )}
            {/* Directories */}
            {dirs.map((entry) => {
              const fullPath =
                currentPath === "." ? entry.name : `${currentPath}/${entry.name}`;
              return (
                <li
                  key={entry.name}
                  className="group flex items-center hover:bg-foreground/5 transition-colors"
                >
                  <button
                    onClick={() => navigateTo(fullPath)}
                    className="flex flex-1 items-center gap-2 px-3 py-1.5 text-xs min-w-0"
                  >
                    <Folder className="h-3.5 w-3.5 shrink-0 text-blue-500" />
                    <span className="truncate">{entry.name}</span>
                  </button>
                  <button
                    onClick={() => handleDownloadFolder(entry)}
                    className="opacity-0 group-hover:opacity-100 transition-opacity px-2 py-1 text-muted-foreground hover:text-foreground"
                    title="Download as zip"
                  >
                    <FolderDown className="h-3.5 w-3.5" />
                  </button>
                </li>
              );
            })}
            {/* Files */}
            {files.map((entry) => {
              const ext = fileExtension(entry.name);
              const icon = EXT_ICONS[ext] || "📄";
              return (
                <li
                  key={entry.name}
                  className="group flex items-center hover:bg-foreground/5 transition-colors"
                >
                  <div className="flex flex-1 items-center gap-2 px-3 py-1.5 text-xs min-w-0">
                    <span className="text-sm shrink-0">{icon}</span>
                    <span className="truncate" title={entry.name}>
                      {entry.name}
                    </span>
                    <span className="text-muted-foreground text-[10px] shrink-0 ml-auto pr-1">
                      {formatSize(entry.size)}
                    </span>
                  </div>
                  <button
                    onClick={() => handleDownloadFile(entry)}
                    className="opacity-0 group-hover:opacity-100 transition-opacity px-2 py-1 text-muted-foreground hover:text-foreground"
                    title="Download"
                  >
                    <Download className="h-3.5 w-3.5" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Footer stats */}
      {listing && (
        <div className="border-t border-border px-3 py-2 text-[10px] text-muted-foreground">
          {dirs.length} folders · {files.length} files
        </div>
      )}
    </div>
  );
}
