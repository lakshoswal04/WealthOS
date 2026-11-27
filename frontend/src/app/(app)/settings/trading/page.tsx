"use client";

import { useEffect, useState } from "react";
import { SettingsCard, SettingsFrame, Toggle, fieldClass } from "@/components/settings/frame";
import { useSettings } from "@/components/trade/settings-context";
import { Loading } from "@/components/trade/primitives";
import { account, type Preferences } from "@/lib/trade-api";

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[var(--hairline)] px-8 py-5 last:border-0">
      <div className="min-w-[220px]">
        <div className="text-body-lg">{label}</div>
        {hint && <div className="mt-0.5 text-small text-[var(--ink-muted)]">{hint}</div>}
      </div>
      <div className="w-full max-w-[280px]">{children}</div>
    </div>
  );
}

export default function TradingPreferencesPage() {
  const { settings, refresh } = useSettings();
  const [form, setForm] = useState<Preferences | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (settings && !form) setForm(settings.preferences); }, [settings, form]);
  if (!form) return <SettingsFrame title="Trading Preferences"><Loading /></SettingsFrame>;

  const set = <K extends keyof Preferences>(k: K, v: Preferences[K]) => { setForm({ ...form, [k]: v }); setSaved(null); };
  async function save() {
    setError(null);
    try {
      const { confirm_ai_orders: _locked, ...editable } = form!;
      void _locked;
      await account.updateSettings({ preferences: editable });
      await refresh();
      setSaved("Saved. New tickets and charts use these defaults.");
    } catch (err) { setError((err as Error).message); }
  }

  return (
    <SettingsFrame title="Trading Preferences">
      <SettingsCard>
        <Row label="Default chart" hint="Opened by Charts when no symbol is chosen.">
          <input value={form.default_symbol} onChange={(e) => set("default_symbol", e.target.value.toUpperCase())} className={fieldClass} />
        </Row>
        <Row label="Default chart interval">
          <select value={form.chart_interval} onChange={(e) => set("chart_interval", e.target.value)} className={fieldClass}>
            {["1m", "5m", "15m", "1h", "1D"].map((i) => <option key={i}>{i}</option>)}
          </select>
        </Row>
        <Row label="Default stock quantity" hint="Shares pre-filled on a stock order.">
          <input type="number" min={1} value={form.default_quantity} onChange={(e) => set("default_quantity", Math.max(1, Number(e.target.value) || 1))} className={fieldClass} />
        </Row>
        <Row label="Default option lots">
          <input type="number" min={1} value={form.default_lots} onChange={(e) => set("default_lots", Math.max(1, Number(e.target.value) || 1))} className={fieldClass} />
        </Row>
        <Row label="Default stock product">
          <select value={form.default_product} onChange={(e) => set("default_product", e.target.value as Preferences["default_product"])} className={fieldClass}>
            <option value="delivery">Delivery</option><option value="intraday">Intraday</option>
          </select>
        </Row>
        <Row label="Default order type">
          <select value={form.default_order_type} onChange={(e) => set("default_order_type", e.target.value as Preferences["default_order_type"])} className={fieldClass}>
            <option value="market">Market</option><option value="limit">Limit</option>
          </select>
        </Row>
        <Row label="1-Tap on by default" hint="Option Buy/Sell on the chart places one lot without the ticket.">
          <div className="flex justify-end"><Toggle label="1-Tap on by default" on={form.one_tap_default} onChange={(v) => set("one_tap_default", v)} /></div>
        </Row>
        <Row label="Confirm AI orders" hint="Always on: the assistant can only propose an order; you confirm it.">
          <div className="flex justify-end"><Toggle label="Confirm AI orders" on disabled onChange={() => {}} /></div>
        </Row>
      </SettingsCard>
      <div className="mt-6 flex items-center gap-4">
        <button onClick={save} className="rounded-full bg-[var(--action)] px-7 py-3 text-body-lg font-semibold text-[var(--action-ink)]">Save preferences</button>
        {saved && <span className="text-body text-[var(--up)]">{saved}</span>}
        {error && <span className="text-body text-[var(--down)]">{error}</span>}
      </div>
    </SettingsFrame>
  );
}
