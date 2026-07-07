"use client";

import { Plus, Upload, Wrench } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { SectionCard as SettingsSectionCard } from "@/components/settings/settings-section";

export default function SkillsSettingsPage() {
  return (
    <div className="space-y-6">
      <SettingsSectionCard
        title="Installed skills"
        description="Skills are contextual capabilities the AI can use automatically. The catalog integration with ClawHub is coming soon."
        action={
          <Button
            size="sm"
            onClick={() => toast.info("Skill catalog integration is coming in a follow-up session.")}
          >
            <Plus className="h-4 w-4 mr-1.5" />
            Browse catalog
          </Button>
        }
      >
        <div className="rounded-xl border border-dashed border-foreground/15 p-8 text-center">
          <Wrench className="mx-auto h-8 w-8 text-muted-foreground mb-3" />
          <p className="font-medium">No skills installed yet</p>
          <p className="text-sm text-muted-foreground mt-1 max-w-md mx-auto">
            The catalog integration with ClawHub will let you install
            community skills (web search, skill creator, browser automation,
            and more) with one click. For now, you can upload a SKILL.md
            file or a skill .zip — coming soon.
          </p>
        </div>
      </SettingsSectionCard>

      <SettingsSectionCard
        title="Upload a skill"
        description="Upload a SKILL.md file or a .zip archive. The skill will be extracted and made available to the AI."
      >
        <div className="rounded-xl border border-dashed border-foreground/15 p-8 text-center">
          <Upload className="mx-auto h-8 w-8 text-muted-foreground mb-3" />
          <p className="font-medium">Upload coming soon</p>
          <p className="text-sm text-muted-foreground mt-1">
            This requires the Hopx sandbox backend to be wired up first.
          </p>
        </div>
      </SettingsSectionCard>
    </div>
  );
}
