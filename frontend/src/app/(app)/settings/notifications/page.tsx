"use client";

import { useState } from "react";
import { SettingsCard, SettingsFrame, Toggle } from "@/components/settings/frame";
import { useSettings } from "@/components/trade/settings-context";
import { Loading } from "@/components/trade/primitives";
import { account, type Notifications } from "@/lib/trade-api";

const ROWS: { key: keyof Notifications; label: string; hint: string }[] = [
  { key: "order_fills", label: "Order fills", hint: "A toast when a 1-Tap order fills on the chart." },
  { key: "price_alerts", label: "Price alerts", hint: "A toast when one of your chart price alerts triggers." },
  { key: "portfolio_alerts", label: "Portfolio alerts", hint: "The unread count on the bell, from the analytics alert rules." },
];

export default function NotificationsPage() {
  const { settings, refresh } = useSettings();
  const [error, setError] = useState<string | null>(null);
  if (!settings) return <SettingsFrame title="Notifications"><Loading /></SettingsFrame>;

  async function flip(key: keyof Notifications, value: boolean) {
    setError(null);
    try { await account.updateSettings({ notifications: { [key]: value } }); await refresh(); }
    catch (err) { setError((err as Error).message); }
  }

  return (
    <SettingsFrame title="Notifications">
      <SettingsCard>
        {ROWS.map((r) => (
          <div key={r.key} className="flex items-center justify-between gap-6 border-b border-[var(--hairline)] px-8 py-5 last:border-0">
            <div>
              <div className="text-body-lg">{r.label}</div>
              <div className="mt-0.5 text-small text-[var(--ink-muted)]">{r.hint}</div>
            </div>
            <Toggle label={r.label} on={settings.notifications[r.key]} onChange={(v) => flip(r.key, v)} />
          </div>
        ))}
      </SettingsCard>
      <p className="mt-5 text-body text-[var(--ink-muted)]">{settings.delivery_note}</p>
      {error && <p className="mt-3 text-body text-[var(--down)]">{error}</p>}
    </SettingsFrame>
  );
}
