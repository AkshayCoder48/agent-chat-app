"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Database, MessageSquare, Plus } from "lucide-react";
import { OnboardingBanner } from "@/components/dashboard/onboarding-banner";
import { PageHeader } from "@/components/dashboard/page-header";
import { QuickActions } from "@/components/dashboard/quick-actions";
import { RecentActivity } from "@/components/dashboard/recent-activity";
import { StatCard } from "@/components/dashboard/stat-card";
import { Button } from "@/components/ui";
import { useAuth } from "@/hooks";
import { apiClient } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { getCollectionInfo, listCollections } from "@/lib/rag-api";
import { cn } from "@/lib/utils";
import type { HealthResponse } from "@/types";
interface ConversationsResponse {
  total?: number;
  items: Array<{ id: string }>;
}

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export default function DashboardPage() {
  const { user } = useAuth();

  // All independent → run in parallel, cached by React Query.
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => apiClient.get<HealthResponse>("/health"),
    staleTime: 60_000,
  });
  const conversations = useQuery({
    queryKey: ["conversations", "count"],
    queryFn: async () => {
      const d = await apiClient.get<ConversationsResponse>("/conversations?limit=1");
      return d.total ?? d.items?.length ?? 0;
    },
  });
  const rag = useQuery({
    queryKey: ["rag", "stats"],
    queryFn: async () => {
      const list = await listCollections();
      const infos = await Promise.all(
        list.items.map((name) => getCollectionInfo(name).catch(() => null)),
      );
      return {
        collections: list.items.length,
        vectors: infos.reduce((s, i) => s + (i?.total_vectors ?? 0), 0),
      };
    },
  });

  const firstName = user?.full_name?.split(" ")[0] || user?.email?.split("@")[0];
  const healthy = !health.isError;

  return (
    <div className="space-y-6 pb-8">
      <OnboardingBanner />

      <PageHeader
        eyebrow="Dashboard"
        title={firstName ? `${getGreeting()}, ${firstName}` : getGreeting()}
        description="Here's what's happening with your workspace today."
        actions={
          <Button asChild>
            <Link href={ROUTES.CHAT}>
              <Plus className="h-4 w-4" />
              New chat
            </Link>
          </Button>
        }
      />

      <div className="border-border bg-card flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border px-4 py-3 text-sm">
        <span className="inline-flex items-center gap-2">
          <span
            aria-hidden
            className={cn(
              "inline-block h-2 w-2 rounded-full",
              healthy ? "bg-emerald-500" : "bg-destructive",
            )}
          />
          <span className="text-foreground font-medium">
            {healthy ? health.data?.status || "Operational" : "API offline"}
          </span>
        </span>
        {health.data?.version && (
          <span className="text-muted-foreground font-mono text-xs">v{health.data.version}</span>
        )}
        <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs">
          <Database className="h-3.5 w-3.5" />
          {rag.data ? `${rag.data.collections} collections` : "—"}
        </span>
      </div>

      <div className="flex items-center justify-between">
        <h2 className="text-muted-foreground font-mono text-xs tracking-wider uppercase">
          Workspace metrics
        </h2>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Conversations"
          value={conversations.isLoading ? "—" : (conversations.data ?? 0).toLocaleString()}
          icon={MessageSquare}
          footer="across all chats"
          loading={conversations.isLoading}
        />
        <StatCard
          label="Knowledge base"
          value={rag.data ? rag.data.vectors.toLocaleString() : "—"}
          unit={rag.data ? `vector${rag.data.vectors === 1 ? "" : "s"}` : undefined}
          icon={Database}
          footer={
            rag.data
              ? `${rag.data.collections} collection${rag.data.collections === 1 ? "" : "s"} indexed`
              : "indexed vectors"
          }
          loading={rag.isLoading}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <RecentActivity />
      </div>

      <div className="grid gap-4 lg:grid-cols-2"></div>

      <QuickActions />
    </div>
  );
}
