"use client";

import { Plus, Blocks } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { SectionCard as SettingsSectionCard } from "@/components/settings/settings-section";

export default function McpsSettingsPage() {
  return (
    <div className="space-y-6">
      <SettingsSectionCard
        title="MCP servers"
        description="Model Context Protocol (MCP) servers expose tools and data sources to the AI. Connect a catalog provider or add a custom one."
        action={
          <Button
            size="sm"
            onClick={() => toast.info("MCP catalog integration is coming in a follow-up session.")}
          >
            <Plus className="h-4 w-4 mr-1.5" />
            Browse catalog
          </Button>
        }
      >
        <div className="rounded-xl border border-dashed border-foreground/15 p-8 text-center">
          <Blocks className="mx-auto h-8 w-8 text-muted-foreground mb-3" />
          <p className="font-medium">No MCP servers connected</p>
          <p className="text-sm text-muted-foreground mt-1 max-w-md mx-auto">
            Connect an MCP server (e.g. filesystem, GitHub, Slack) to give
            the AI access to external tools and data sources. Catalog
            integration is coming soon.
          </p>
        </div>
      </SettingsSectionCard>
    </div>
  );
}
