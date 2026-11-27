import { V1, del, patch, post, put, q, request } from "./http";
import type { BrokerStatus, MemoryItem, MemoryState, Notifications, Preferences, PromptBook, SyncResult, UserSettings } from "./types";

export const account = {
  settings: () => request<UserSettings>(`${V1}/me/settings`),
  updateSettings: (body: { preferences?: Partial<Preferences>; notifications?: Partial<Notifications> }) =>
    patch<UserSettings>(`${V1}/me/settings`, body),
  memory: () => request<MemoryState>(`${V1}/me/memory`),
  addMemory: (section: string, text: string) => post<MemoryItem>(`${V1}/me/memory`, { section, text }),
  deleteMemory: (id: number) => del(`${V1}/me/memory/${id}`),
  setMemoryPaused: (paused: boolean) => put<{ paused: boolean }>(`${V1}/me/memory/state`, { paused }),
  brokers: () => request<{ brokers: BrokerStatus[]; note: string }>(`${V1}/me/brokers`),
  saveUpstox: (api_key: string, api_secret: string) => put<BrokerStatus>(`${V1}/me/brokers/upstox`, { api_key, api_secret }),
  upstoxLogin: () => post<{ authorization_url: string; redirect_uri: string; expires_at: string }>(`${V1}/me/brokers/upstox/login`, {}),
  upstoxSync: () => post<SyncResult>(`${V1}/me/brokers/upstox/sync`, {}),
  upstoxDisconnect: (forget = false) => request<BrokerStatus>(`${V1}/me/brokers/upstox${q({ forget })}`, { method: "DELETE" }),
  changePassword: (current_password: string, new_password: string) =>
    post<{ changed: boolean }>(`${V1}/me/password`, { current_password, new_password }),
  deleteAccount: (password: string) => post<{ deleted: boolean }>(`${V1}/me/delete`, { password }),
  promptBook: (lang: "en" | "hi") => request<PromptBook>(`${V1}/me/prompt-book${q({ lang })}`),
};
