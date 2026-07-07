"use client";

import type { ReactNode } from "react";
import { Blocks, KeyRound, Palette, Settings, Shield, Slash, UserCircle, Wrench } from "lucide-react";

import { ROUTES } from "@/lib/constants";
import { PageHeader } from "@/components/dashboard/page-header";
import { PageTabs, type PageTab } from "@/components/dashboard/page-tabs";

const SETTINGS_TABS: PageTab[] = [
  { label: "Profile", href: ROUTES.SETTINGS_PROFILE, icon: UserCircle },
  { label: "Account", href: ROUTES.SETTINGS_ACCOUNT, icon: Shield },
  { label: "Config", href: ROUTES.SETTINGS_CONFIG, icon: Settings },
  { label: "Slash commands", href: ROUTES.SETTINGS_SLASH_COMMANDS, icon: Slash },
  { label: "Skills", href: ROUTES.SETTINGS_SKILLS, icon: Wrench },
  { label: "MCPs", href: ROUTES.SETTINGS_MCPS, icon: Blocks },
  { label: "Tools", href: ROUTES.SETTINGS_TOOLS, icon: Wrench },
  { label: "Env vars", href: ROUTES.SETTINGS_ENV, icon: KeyRound },
  { label: "Appearance", href: ROUTES.SETTINGS_APPEARANCE, icon: Palette },
];

export default function SettingsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-6 pb-8">
      <PageHeader
        eyebrow="Settings"
        title="Settings"
        description="Manage your account, config, slash commands, skills, MCPs, tools, env vars, and appearance."
      />
      <PageTabs tabs={SETTINGS_TABS} />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
