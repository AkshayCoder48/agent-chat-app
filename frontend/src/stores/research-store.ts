"use client";

import { create } from "zustand";
import type { ResearchTodo } from "@/types";

interface ResearchTurn {
  todos: ResearchTodo[];
  stopped?: boolean;
  contextUsed?: number;
  contextLimit?: number;
  subagentStatuses?: Array<{ id: string; name: string; status: string }>;
}

interface ResearchState {
  byTurn: Record<string, ResearchTurn>;
  applyTodoEvent: (eventType: string, todo: ResearchTodo) => void;
  reset: (turnId?: string) => void;
}

// Stub store — deep research is disabled in this build.
// Kept so that components compiling against `useResearchStore` still type-check.
export const useResearchStore = create<ResearchState>(() => ({
  byTurn: {},
  applyTodoEvent: () => {},
  reset: () => {},
}));
