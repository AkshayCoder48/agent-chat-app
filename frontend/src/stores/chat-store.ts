"use client";

import { create } from "zustand";
import type { ChatMessage, MessagePart, ToolCall } from "@/types";

function newPartId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `part-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

const PERSIST_KEY = "chat-store:messages";
const PERSIST_CONV_KEY = "chat-store:conversationId";

/** Load persisted messages from sessionStorage. Returns [] when missing or
 *  malformed. We persist across reloads so a mid-generation refresh doesn't
 *  wipe the in-flight assistant message. */
function loadPersisted(): ChatMessage[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.sessionStorage.getItem(PERSIST_KEY);
    if (!raw) return [];
    const data = JSON.parse(raw) as ChatMessage[];
    // Rehydrate Date objects (JSON.stringify turns them into strings).
    return data.map((m) => ({ ...m, timestamp: new Date(m.timestamp) }));
  } catch {
    return [];
  }
}

function savePersisted(messages: ChatMessage[]): void {
  if (typeof window === "undefined") return;
  try {
    // Strip out temporary-id flags — they're meaningless across reloads.
    const safe = messages
      .filter((m) => !m.isTemporaryId || m.content)
      .slice(-50); // cap to last 50 to avoid quota errors
    window.sessionStorage.setItem(PERSIST_KEY, JSON.stringify(safe));
  } catch {
    // Quota exceeded / disabled — ignore.
  }
}

interface ChatState {
  messages: ChatMessage[];
  isStreaming: boolean;

  addMessage: (message: ChatMessage) => void;
  updateMessage: (id: string, updater: (msg: ChatMessage) => ChatMessage) => void;
  updateMessagesWhere: (
    predicate: (msg: ChatMessage) => boolean,
    updater: (msg: ChatMessage) => ChatMessage,
  ) => void;
  addToolCall: (messageId: string, toolCall: ToolCall) => void;
  updateToolCall: (messageId: string, toolCallId: string, update: Partial<ToolCall>) => void;
  /** Append a streamed text delta — extends the trailing text part or
   *  starts a new one, keeping the flat ``content`` aggregate in sync. */
  appendTextDelta: (messageId: string, text: string) => void;
  /** Append a streamed reasoning delta — same logic for "thinking" parts. */
  appendThinkingDelta: (messageId: string, text: string) => void;
  /** Add a tool call as an ordered part (and to the flat ``toolCalls``). */
  addToolCallPart: (messageId: string, toolCall: ToolCall) => void;
  /** Update a tool call inside its part and the flat ``toolCalls``. */
  updateToolCallPart: (messageId: string, toolCallId: string, update: Partial<ToolCall>) => void;
  setStreaming: (streaming: boolean) => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: loadPersisted(),
  isStreaming: false,

  addMessage: (message) =>
    set((state) => {
      const messages = [...state.messages, message];
      savePersisted(messages);
      return { messages };
    }),

  updateMessage: (id, updater) =>
    set((state) => {
      const messages = state.messages.map((msg) => (msg.id === id ? updater(msg) : msg));
      savePersisted(messages);
      return { messages };
    }),

  updateMessagesWhere: (predicate, updater) =>
    set((state) => {
      const messages = state.messages.map((msg) => (predicate(msg) ? updater(msg) : msg));
      savePersisted(messages);
      return { messages };
    }),

  addToolCall: (messageId, toolCall) =>
    set((state) => {
      const messages = state.messages.map((msg) =>
        msg.id === messageId ? { ...msg, toolCalls: [...(msg.toolCalls || []), toolCall] } : msg,
      );
      savePersisted(messages);
      return { messages };
    }),

  updateToolCall: (messageId, toolCallId, update) =>
    set((state) => {
      const messages = state.messages.map((msg) =>
        msg.id === messageId
          ? {
              ...msg,
              toolCalls: msg.toolCalls?.map((tc) =>
                tc.id === toolCallId ? { ...tc, ...update } : tc,
              ),
            }
          : msg,
      );
      savePersisted(messages);
      return { messages };
    }),

  appendTextDelta: (messageId, text) =>
    set((state) => {
      const messages = state.messages.map((msg) => {
        if (msg.id !== messageId) return msg;
        const parts: MessagePart[] = msg.parts ? [...msg.parts] : [];
        const last = parts[parts.length - 1];
        if (last && last.type === "text") {
          parts[parts.length - 1] = { ...last, content: (last.content ?? "") + text };
        } else {
          parts.push({ id: newPartId(), type: "text" as const, content: text });
        }
        return { ...msg, parts, content: msg.content + text };
      });
      savePersisted(messages);
      return { messages };
    }),

  appendThinkingDelta: (messageId, text) =>
    set((state) => {
      const messages = state.messages.map((msg) => {
        if (msg.id !== messageId) return msg;
        const parts: MessagePart[] = msg.parts ? [...msg.parts] : [];
        const last = parts[parts.length - 1];
        if (last && last.type === "thinking") {
          parts[parts.length - 1] = { ...last, content: (last.content ?? "") + text };
        } else {
          parts.push({ id: newPartId(), type: "thinking" as const, content: text });
        }
        return { ...msg, parts, thinking: (msg.thinking ?? "") + text };
      });
      savePersisted(messages);
      return { messages };
    }),

  addToolCallPart: (messageId, toolCall) =>
    set((state) => {
      const messages = state.messages.map((msg) =>
        msg.id === messageId
          ? {
              ...msg,
              parts: [...(msg.parts ?? []), { id: newPartId(), type: "tool" as const, toolCall }],
              toolCalls: [...(msg.toolCalls || []), toolCall],
            }
          : msg,
      );
      savePersisted(messages);
      return { messages };
    }),

  updateToolCallPart: (messageId, toolCallId, update) =>
    set((state) => {
      const messages = state.messages.map((msg) =>
        msg.id === messageId
          ? {
              ...msg,
              parts: msg.parts?.map((p) =>
                p.type === "tool" && p.toolCall && p.toolCall.id === toolCallId
                  ? { ...p, toolCall: { ...p.toolCall, ...update } }
                  : p,
              ),
              toolCalls: msg.toolCalls?.map((tc) =>
                tc.id === toolCallId ? { ...tc, ...update } : tc,
              ),
            }
          : msg,
      );
      savePersisted(messages);
      return { messages };
    }),

  setStreaming: (streaming) => set({ isStreaming: streaming }),

  clearMessages: () => {
    if (typeof window !== "undefined") {
      window.sessionStorage.removeItem(PERSIST_KEY);
      window.sessionStorage.removeItem(PERSIST_CONV_KEY);
    }
    set({ messages: [] });
  },
}));

/** Track which conversation the persisted messages belong to — so switching
 *  to a different chat doesn't restore the previous chat's messages. */
export function setPersistedConversationId(id: string | null): void {
  if (typeof window === "undefined") return;
  if (id === null) {
    window.sessionStorage.removeItem(PERSIST_CONV_KEY);
  } else {
    window.sessionStorage.setItem(PERSIST_CONV_KEY, id);
  }
}

export function getPersistedConversationId(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(PERSIST_CONV_KEY);
}

/** Drop persisted messages when they belong to a different conversation. */
export function reconcilePersisted(activeConversationId: string | null): void {
  const stored = getPersistedConversationId();
  if (stored !== (activeConversationId ?? null)) {
    if (typeof window !== "undefined") {
      window.sessionStorage.removeItem(PERSIST_KEY);
    }
    useChatStore.setState({ messages: [] });
    setPersistedConversationId(activeConversationId);
  }
}
