"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { account, type BrokerStatus, type SyncResult } from "@/lib/trade-api";
import { Badge, Button, Card, CardBody, CardHeader, ErrorNote } from "@/components/ui";

/**
 * Import holdings from a real broker. Upstox is the supported broker: once
 * connected (Settings → Broker APIs) its long-term holdings sync straight
 * into the analytics. CSV import remains available below this card.
 */
export function LinkedAccounts() {
  const [upstox, setUpstox] = useState<BrokerStatus | null>(null);
  const [result, setResult] = useState<SyncResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setUpstox((await account.brokers()).brokers.find((b) => b.broker === "upstox") ?? null); }
    catch (err) { setError((err as Error).message); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function sync() {
    setBusy(true); setError(null);
    try { setResult(await account.upstoxSync()); await load(); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  const connected = upstox?.state === "connected";
  return (
    <Card>
      <CardHeader eyebrow="Broker" title="Import from Upstox"
        subtitle="Sync your real long-term holdings from your Upstox account. Only holdings are read; nothing is ever traded."
        action={upstox && <Badge tone={connected ? "good" : upstox.state === "expired" ? "warning" : "neutral"}>
          {connected ? "Connected" : upstox.state === "expired" ? "Session expired" : "Not connected"}</Badge>} />
      <CardBody>
        {error && <ErrorNote message={error} />}
        {connected ? (
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={sync} disabled={busy}>{busy ? "Syncing…" : "Sync holdings now"}</Button>
            <span className="text-small text-[var(--ink-muted)]">
              Last sync: {upstox?.last_successful_sync_at ? new Date(upstox.last_successful_sync_at).toLocaleString("en-IN") : "never"}
            </span>
          </div>
        ) : (
          <p className="text-body text-[var(--ink-secondary)]">
            {upstox?.state === "expired" ? "Your Upstox session ended (sessions close at 03:30 IST daily). " : ""}
            <Link href="/settings/brokers" className="text-[var(--accent)] underline-offset-2 hover:underline">
              {upstox?.credentials_saved ? "Log in to Upstox" : "Connect Upstox"}
            </Link>{" "}to import your holdings.
          </p>
        )}
        {result && (
          <p className="mt-3 text-small text-[var(--ink-secondary)]">
            {result.run.status === "success"
              ? `Read ${result.run.holdings_seen} holding(s): ${result.run.holdings_created} added, ${result.run.holdings_updated} updated` +
                (result.run.details.unknown_symbols_skipped ? `; ${result.run.details.unknown_symbols_skipped} outside the NIFTY 100 universe skipped.` : ".")
              : `Sync failed: ${result.run.error_message}`}
          </p>
        )}
      </CardBody>
    </Card>
  );
}
