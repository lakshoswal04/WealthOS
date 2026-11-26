"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type LinkedAccount, type SyncRun } from "@/lib/api";
import { shortDate, titleCase } from "@/lib/format";
import { Badge, Button, Card, CardBody, CardHeader, ErrorNote, Field, inputClass } from "@/components/ui";

export function LinkedAccounts() {
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);
  const [notice, setNotice] = useState("");
  const [provider, setProvider] = useState("sandbox");
  const [reference, setReference] = useState("SBX0001");
  const [history, setHistory] = useState<Record<number, SyncRun[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    const data = await api.linkedAccounts(); setAccounts(data.accounts); setNotice(data.simulation_notice);
  }, []);
  useEffect(() => { refresh().catch((err: Error) => setError(err.message)).finally(() => setLoading(false)); }, [refresh]);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await action(); await refresh(); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }
  async function showHistory(id: number) {
    const response = await api.syncHistory(id);
    setHistory((previous) => ({ ...previous, [id]: response.runs }));
  }
  return <Card className="rise mt-5">
    <CardHeader title="Simulated account linking" subtitle="Try the brokerage integration in a sandbox. No live broker is contacted." action={<Badge tone="warning">Simulation</Badge>} />
    <CardBody>
      <p className="text-small text-[var(--ink-secondary)]">{notice || "Sandbox accounts use generated data and do not connect to a real brokerage."} Syncing adds simulated transactions and creates or updates holdings in your portfolio, including matching existing symbols.</p>
      <div className="mt-4 grid items-end gap-3 sm:grid-cols-[1fr_1fr_auto]">
        <Field label="Simulated provider"><select className={inputClass} value={provider} onChange={(event) => setProvider(event.target.value)}>
          <option value="sandbox">Sandbox</option><option value="zerodha_sandbox">Zerodha sandbox</option><option value="upstox_sandbox">Upstox sandbox</option><option value="groww_sandbox">Groww sandbox</option>
        </select></Field>
        <Field label="Sandbox account reference"><input className={inputClass} maxLength={64} value={reference} onChange={(event) => setReference(event.target.value)} /></Field>
        <Button disabled={busy || !reference.trim()} onClick={() => run(async () => { await api.linkSandbox(provider, reference.trim()); })}>Create simulated link</Button>
      </div>
      {error && <div className="mt-4"><ErrorNote message={error} /></div>}
      {loading && <p className="mt-4 text-small text-[var(--ink-secondary)]">Loading accounts…</p>}
      <ul className="mt-4 space-y-3">{accounts.map((account) => <li key={account.id} className="rounded-[var(--radius-sm)] border border-[var(--hairline)] p-4">
        <div className="flex flex-wrap items-center gap-2"><strong className="text-body">{account.display_name}</strong><Badge tone="warning">Simulated</Badge><Badge>{titleCase(account.status)}</Badge></div>
        <p className="mt-2 text-small text-[var(--ink-secondary)]">Last successful sync: {account.last_successful_sync_at ? shortDate(account.last_successful_sync_at) : "Never"}{account.last_sync_error ? ` · ${account.last_sync_error}` : ""}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {account.status !== "disconnected" && <Button size="sm" disabled={busy} onClick={() => { if (window.confirm("Sync simulated data into your portfolio? This creates or updates holdings, including matching existing symbols, and adds simulated transactions.")) void run(async () => { await api.syncAccount(account.id); await showHistory(account.id); }); }}>Sync simulated data</Button>}
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(() => showHistory(account.id))}>View sync history</Button>
          {account.status !== "disconnected" && <Button size="sm" variant="ghost" disabled={busy} onClick={() => { if (window.confirm("Disconnect this simulated account? Its sync history will be kept.")) void run(async () => { await api.disconnectAccount(account.id); }); }}>Disconnect</Button>}
        </div>
        {history[account.id] && <div className="mt-3 text-small text-[var(--ink-secondary)]"><p className="font-medium">Sync history</p>{history[account.id].length === 0 ? <p>No syncs yet.</p> : <ul>{history[account.id].map((run) => <li key={run.id} className="mt-1">{run.started_at ? shortDate(run.started_at) : "Unknown date"} · {titleCase(run.status)} · {run.holdings_created} holdings created, {run.holdings_updated} updated, {run.transactions_created} transactions added{run.error_message ? ` · ${run.error_message}` : ""}</li>)}</ul>}</div>}
      </li>)}</ul>
    </CardBody>
  </Card>;
}
