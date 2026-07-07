"use client";

import { Blocks, Wrench, Server } from "lucide-react";
import Link from "next/link";

import { SectionCard as SettingsSectionCard } from "@/components/settings/settings-section";
import { ROUTES } from "@/lib/constants";

export default function PluginsSettingsPage() {
  return (
    <div className="space-y-6">
      <SettingsSectionCard
        title="Plugins (deprecated)"
        description="The plugin system has been replaced by Skills (ClawHub catalog) and MCP servers. Use the pages below for the same functionality."
      >
        <div className="rounded-xl border border-dashed border-foreground/15 p-8 text-center">
          <Blocks className="mx-auto h-8 w-8 text-muted-foreground mb-3" />
          <p className="font-medium">Plugins have been retired</p>
          <p className="text-sm text-muted-foreground mt-1 max-w-md mx-auto">
            Skills and MCP servers cover everything plugins used to do, with a
            cleaner extension model and tighter agent integration. Browse the
            catalog or wire up an MCP server below.
          </p>
          <div className="mt-5 flex items-center justify-center gap-3">
            <Link
              href={ROUTES.SETTINGS_SKILLS}
              className="inline-flex items-center gap-2 rounded-md border border-foreground/15 px-3 py-1.5 text-sm hover:bg-foreground/[0.03]"
            >
              <Wrench className="h-4 w-4" /> Skills
            </Link>
            <Link
              href={ROUTES.SETTINGS_MCPS}
              className="inline-flex items-center gap-2 rounded-md border border-foreground/15 px-3 py-1.5 text-sm hover:bg-foreground/[0.03]"
            >
              <Server className="h-4 w-4" /> MCP servers
            </Link>
          </div>
        </div>
      </SettingsSectionCard>
    </div>
  );
}
