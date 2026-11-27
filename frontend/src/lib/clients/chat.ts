import { V1, del, post, request } from "./http";
import type { ChatMessage, ChatThread } from "./types";

export const chat = {
  threads: () => request<{ threads: ChatThread[] }>(`${V1}/chat/threads`),
  thread: (id: number) => request<ChatThread>(`${V1}/chat/threads/${id}`),
  create: (title?: string | null, symbol?: string | null) =>
    post<ChatThread>(`${V1}/chat/threads`, { title, context: symbol ? { symbol } : null }),
  send: (threadId: number, content: string, symbol?: string | null) =>
    post<{ thread: ChatThread; message: ChatMessage }>(`${V1}/chat/threads/${threadId}/messages`,
      { content, context: symbol ? { symbol } : null }),
  remove: (id: number) => del(`${V1}/chat/threads/${id}`),
};
