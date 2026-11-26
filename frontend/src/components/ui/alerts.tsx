"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type AlertGeneration, type PortfolioAlert } from "@/lib/api";
import { shortDate, titleCase } from "@/lib/format";
import { Badge, Button, Card, CardBody, CardHeader, ErrorNote } from "@/components/ui";

export function AlertsPanel() {
  const [alerts, setAlerts] = useState<PortfolioAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AlertGeneration | null>(null);
  const refresh = useCallback(async () => {
    setAlerts((await api.alerts()).alerts);
  }, []);
  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message)).finally(() => setLoading(false));
  }, [refresh]);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await action(); await refresh(); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <Card className="rise mt-5">
      <CardHeader title="Portfolio alerts" subtitle="Measurements that cross a threshold, with their evidence. Generate a fresh check when you need one."
        action={<Button size="sm" disabled={busy} onClick={() => run(async () => setResult(await api.generateAlerts()))}>{busy ? "Checking…" : "Check portfolio"}</Button>} />
      <CardBody>
        {error && <ErrorNote message={error} />}
        {loading && <p className="text-small text-[var(--ink-secondary)]">Loading alerts…</p>}
        {result && <div role="status" className="mb-4 text-small text-[var(--ink-secondary)]">
          {result.generated_count} new alerts. {result.rejected.length > 0 && `${result.rejected.length} rules were rejected during verification. `}
          {result.suppressed_as_already_open?.length > 0 && <p>Already checked recently: {result.suppressed_as_already_open.map(titleCase).join(", ")}.</p>}
          {result.rejected.map((item, index) => <p key={`${item.rule}-${index}`}>{titleCase(item.rule)}: {item.reason}</p>)}
          {Object.entries(result.measurement_failures).map(([name, reason]) => <p key={name}>{titleCase(name)}: {reason}</p>)}
        </div>}
        {!loading && !error && alerts.length === 0 && <p className="text-small text-[var(--ink-secondary)]">No alerts yet. Run a check to evaluate your portfolio.</p>}
        <ul className="space-y-3">
          {alerts.map((alert) => <li key={alert.id} className="rounded-[var(--radius-sm)] border border-[var(--hairline)] bg-[var(--surface-1)] p-4">
            <div className="flex flex-wrap items-center gap-2"><strong className="text-body">{alert.title}</strong><Badge tone={alert.severity === "critical" ? "critical" : alert.severity === "warning" ? "warning" : "neutral"}>{titleCase(alert.severity)}</Badge>{!alert.is_read && <Badge tone="accent">Unread</Badge>}</div>
            <p className="mt-2 text-small text-[var(--ink-secondary)]">{alert.message}</p>
            <p className="mt-2 text-caption text-[var(--ink-muted)]">{alert.created_at ? shortDate(alert.created_at) : ""}{alert.threshold != null ? ` · Threshold: ${alert.threshold}` : ""}</p>
            <div className="mt-3 flex gap-2">{!alert.is_read && <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(async () => { await api.readAlert(alert.id); })}>Mark read</Button>}
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => { if (window.confirm("Dismiss this alert permanently?")) void run(async () => { await api.dismissAlert(alert.id); }); }}>Dismiss</Button></div>
          </li>)}
        </ul>
      </CardBody>
    </Card>
  );
}
