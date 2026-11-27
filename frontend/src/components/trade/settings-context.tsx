"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { account, type UserSettings } from "@/lib/trade-api";

interface SettingsState { settings: UserSettings | null; refresh: () => Promise<void> }

const SettingsContext = createContext<SettingsState>({ settings: null, refresh: async () => {} });

/** The user's trading preferences and notification choices, loaded once per session. */
export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const refresh = useCallback(async () => {
    try {
      const next = await account.settings();
      // Only a well-formed answer replaces the defaults.
      if (next?.preferences && next?.notifications) setSettings(next);
    } catch { /* defaults apply */ }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  const value = useMemo(() => ({ settings, refresh }), [settings, refresh]);
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export const useSettings = () => useContext(SettingsContext);
