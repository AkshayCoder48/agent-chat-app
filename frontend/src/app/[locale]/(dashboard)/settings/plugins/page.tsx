"use client";

import { Plus, Blocks } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { SectionCard as SettingsSectionCard } from "@/components/settings/settings-section";

export default function PluginsSettingsPage() {
  return (
    <div className="space-y-6">
      <SettingsSectionCard
        title="Installed plugins"
        description="Plugins are community-contributed extensions installed from the ClawHub catalog."
        action={
          <Button
            size="sm"
            onClick={() => toast.info("Plugin catalog integration is coming in a follow-up session.")}
          >
            <Plus className="h-4 w-4 mr-1.5" />
            Browse catalog
          </Button>
        }
      >
        <div className="rounded-xl border border-dashed border-foreground/15 p-8 text-center">
          <Blocks className="mx-auto h-8 w-8 text-muted-foreground mb-3" />
          <p className="font-medium">No plugins installed</p>
          <p className="text-sm text-muted-foreground mt-1 max-w-md mx-auto">
            The catalog integration with ClawHub will let you browse and
            install community plugins sorted by download count.
          </p>
        </div>
      </SettingsSectionCard>
    </div>
  );
}
