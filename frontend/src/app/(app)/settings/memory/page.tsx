"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { SettingsCard, SettingsFrame, Toggle, fieldClass } from "@/components/settings/frame";
import { Icon, Loading } from "@/components/trade/primitives";
import { account, type MemoryState } from "@/lib/trade-api";

export default function MemoryPage() {
  const [state, setState] = useState<MemoryState | null>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => setState(await account.memory()), []);
  useEffect(() => { void load(); }, [load]);

  if (!state) return <SettingsFrame title="Memory"><Loading /></SettingsFrame>;

  async function add(section: string) {
    setError(null);
    try { await account.addMemory(section, text); setText(""); setAdding(null); await load(); }
    catch (err) { setError((err as Error).message); }
  }
  function download() {
    const blob = new Blob([JSON.stringify(state, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "wealthos-memory.json";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <SettingsFrame title="Memory" hint="What the assistant remembers about you, so answers fit how you trade. It is told these facts; it never treats them as figures."
      action={
        <button onClick={download} disabled={!state.memories.length}
          className="flex items-center gap-2 rounded-full border border-[var(--hairline-strong)] px-5 py-2.5 text-body-lg text-[var(--ink-secondary)] hover:bg-[var(--surface-3)] disabled:opacity-40">
          <Icon name="download" size={18} /> Download
        </button>
      }>
      <SettingsCard className="flex items-center justify-between px-7 py-5">
        <span className="flex items-center gap-3 text-body-lg">
          <span className={`h-2.5 w-2.5 rounded-full ${state.paused ? "bg-[var(--ink-faint)]" : "bg-[var(--up)]"}`} />
          {state.paused ? "Memory is paused" : "Memory is on"}
        </span>
        <span className="flex items-center gap-3 text-body-lg text-[var(--ink-secondary)]">
          Pause memory
          <Toggle label="Pause memory" on={state.paused} onChange={async (v) => { await account.setMemoryPaused(v); await load(); }} />
        </span>
      </SettingsCard>

      <h2 className="mt-10 flex items-center gap-2 text-h3 font-semibold">Your profile</h2>
      <p className="mt-3 text-body-lg text-[var(--ink-secondary)]">
        {state.memories.length === 0
          ? <>Nothing remembered yet. As you chat about how you trade, your profile fills in here. <Link href="/home" className="text-[var(--series-1)] hover:underline">Go to chat</Link></>
          : <>Facts you added, or that the assistant picked up from chat. Remove anything that is wrong.</>}
      </p>
      {error && <p className="mt-3 text-body text-[var(--down)]">{error}</p>}

      <div className="mt-6 space-y-5">
        {Object.entries(state.sections).map(([key, label]) => {
          const items = state.memories.filter((m) => m.section === key);
          return (
            <SettingsCard key={key} className="px-7 py-6">
              <div className="flex items-center justify-between">
                <h3 className="text-body-lg font-semibold">{label}</h3>
                <button aria-label={`Add to ${label}`} onClick={() => { setAdding(adding === key ? null : key); setText(""); }}
                  className="rounded-full p-1.5 text-[var(--ink-secondary)] hover:bg-[var(--surface-3)] hover:text-[var(--ink-primary)]">
                  <Icon name="plus" size={20} />
                </button>
              </div>
              {items.length === 0 && adding !== key && (
                <p className="mt-3 text-body text-[var(--ink-muted)]">Nothing here yet. Add it yourself, or it fills in as you chat.</p>
              )}
              <ul className="mt-3 space-y-2">
                {items.map((m) => (
                  <li key={m.id} className="group flex items-center justify-between gap-3 rounded-[var(--radius-sm)] bg-[var(--surface-2)] px-4 py-2.5 text-body">
                    <span>{m.text}{m.source === "chat" && <span className="ml-2 rounded-full border border-[var(--hairline-strong)] px-2 py-[1px] text-micro text-[var(--ink-muted)]">from chat</span>}</span>
                    <button aria-label="Forget this" onClick={async () => { await account.deleteMemory(m.id); await load(); }}
                      className="text-[var(--ink-faint)] opacity-60 hover:text-[var(--down)] group-hover:opacity-100"><Icon name="trash" size={15} /></button>
                  </li>
                ))}
              </ul>
              {adding === key && (
                <div className="mt-3 flex gap-2">
                  <input autoFocus value={text} maxLength={280} onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") void add(key); if (e.key === "Escape") setAdding(null); }}
                    placeholder="e.g. Trades NIFTY weekly options" className={fieldClass} />
                  <button onClick={() => add(key)} className="rounded-full bg-[var(--action)] px-5 text-body font-semibold text-[var(--action-ink)]">Add</button>
                </div>
              )}
            </SettingsCard>
          );
        })}
      </div>
    </SettingsFrame>
  );
}
