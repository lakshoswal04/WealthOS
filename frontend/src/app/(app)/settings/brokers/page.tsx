"use client";

import clsx from "clsx";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { SettingsCard, SettingsFrame, fieldClass } from "@/components/settings/frame";
import { Icon, Loading } from "@/components/trade/primitives";
import { account, type BrokerStatus, type SyncResult } from "@/lib/trade-api";

const TABS: { key: BrokerStatus["broker"]; name: string; hue: number }[] = [
  { key: "zerodha", name: "Zerodha", hue: 12 }, { key: "groww", name: "Groww", hue: 215 },
  { key: "dhan", name: "Dhan", hue: 150 }, { key: "upstox", name: "Upstox", hue: 270 },
];

const STEPS = [
  { title: "Sign up / Login", body: "Open the Upstox developer console and log in with your Upstox trading account. Open an Upstox account first if you do not have one." },
  { title: "Create an app", body: "Choose “New App”. Give it any name, for example WealthOS. Upstox developer apps are free." },
  { title: "Set the redirect URL", body: "Paste this exact address into the app’s Redirect URL field. Upstox only ever returns to the address you register." },
  { title: "Copy the API key", body: "Open the app you created and copy its API key." },
  { title: "Copy the API secret", body: "Copy the app’s API secret too. Both are encrypted before they are stored, and never shown again." },
  { title: "Log in with Upstox", body: "Upstox asks you to approve access. Approving returns you here with a session that lasts until 03:30 IST tomorrow; log in again each trading day." },
  { title: "Connected", body: "Live option chains, open interest, futures and real-time prices now come from your account. Orders stay on paper." },
];

export default function BrokersPage() {
  return <Suspense fallback={<Loading />}><Brokers /></Suspense>;
}

function Brokers() {
  const params = useSearchParams();
  const [tab, setTab] = useState<BrokerStatus["broker"]>("upstox");
  const [brokers, setBrokers] = useState<BrokerStatus[] | null>(null);
  const [note, setNote] = useState("");
  const banner = params.get("upstox");
  const bannerMessage = params.get("message");

  const load = useCallback(async () => {
    const r = await account.brokers();
    setBrokers(r.brokers);
    setNote(r.note);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const current = brokers?.find((b) => b.broker === tab);

  return (
    <SettingsFrame title="Broker APIs">
      {banner === "connected" && (
        <div className="mb-6 rounded-[var(--radius)] border border-[color-mix(in_oklab,var(--up)_40%,transparent)] px-5 py-3 text-body text-[var(--up)]">
          Upstox is connected. Live option data and real-time prices are on.
        </div>
      )}
      {banner === "error" && (
        <div className="mb-6 rounded-[var(--radius)] border border-[color-mix(in_oklab,var(--down)_40%,transparent)] px-5 py-3 text-body text-[var(--down)]">
          {bannerMessage || "The Upstox login did not complete."}
        </div>
      )}

      <div className="mb-8 flex flex-wrap gap-3">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={clsx("flex items-center gap-2.5 rounded-full border px-5 py-2.5 text-body-lg transition-colors",
              tab === t.key ? "border-[var(--ink-secondary)] bg-[var(--surface-2)] text-[var(--ink-primary)]"
                : "border-[var(--hairline-strong)] text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]")}>
            <span className="flex h-7 w-7 items-center justify-center rounded-full text-caption font-bold text-white"
              style={{ background: `hsl(${t.hue} 55% 42%)` }}>{t.name[0]}</span>
            {t.name}
          </button>
        ))}
      </div>

      {!brokers ? <Loading /> : current && !current.supported ? (
        <SettingsCard className="px-10 py-12 text-center">
          <div className="text-h3 font-semibold">{current.name} isn&apos;t supported yet</div>
          <p className="mx-auto mt-3 max-w-lg text-body-lg text-[var(--ink-secondary)]">{current.reason}</p>
          <button onClick={() => setTab("upstox")} className="mt-6 rounded-full bg-[var(--action)] px-6 py-3 text-body-lg font-semibold text-[var(--action-ink)]">
            Set up Upstox instead
          </button>
        </SettingsCard>
      ) : current && <UpstoxWizard status={current} onChange={load} />}

      <p className="mt-8 flex items-start gap-2.5 text-body text-[var(--ink-muted)]">
        <Icon name="lock" size={17} className="mt-0.5" />
        {note || "Credentials are encrypted at rest."}
      </p>
    </SettingsFrame>
  );
}

function initialStep(s: BrokerStatus) {
  if (s.state === "connected") return 6;
  if (s.credentials_saved) return 5;
  return 0;
}

function UpstoxWizard({ status, onChange }: { status: BrokerStatus; onChange: () => Promise<void> }) {
  const [step, setStep] = useState(initialStep(status));
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [walkthrough, setWalkthrough] = useState(false);
  const [sync, setSync] = useState<SyncResult | null>(null);
  useEffect(() => { setStep(initialStep(status)); }, [status.state, status.credentials_saved]); // eslint-disable-line react-hooks/exhaustive-deps

  const s = STEPS[step];

  async function next() {
    setError(null);
    if (step === 3 && apiKey.trim().length < 8) { setError("Paste the API key from your Upstox app."); return; }
    if (step === 4) {
      if (apiSecret.trim().length < 6) { setError("Paste the API secret from your Upstox app."); return; }
      setBusy(true);
      try { await account.saveUpstox(apiKey.trim(), apiSecret.trim()); setApiSecret(""); await onChange(); }
      catch (err) { setError((err as Error).message); setBusy(false); return; }
      setBusy(false);
    }
    if (step === 5) {
      setBusy(true);
      try { window.location.href = (await account.upstoxLogin()).authorization_url; }
      catch (err) { setError((err as Error).message); setBusy(false); }
      return;
    }
    setStep((v) => Math.min(v + 1, 6));
  }

  async function doSync() {
    setBusy(true); setError(null);
    try { setSync(await account.upstoxSync()); await onChange(); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  return (
    <>
      <SettingsCard className="px-10 pb-10 pt-11">
        <div className="mb-10 grid grid-cols-7 gap-2">
          {STEPS.map((_, i) => (
            <div key={i} className={clsx("h-1 rounded-full", i <= step ? "bg-[var(--ink-primary)]" : "bg-[var(--surface-4)]")} />
          ))}
        </div>
        <div className="flex items-center justify-between text-small uppercase tracking-[0.12em] text-[var(--ink-muted)]">
          <span>Step {step + 1} of 7</span><span className="normal-case tracking-normal">Upstox</span>
        </div>
        <h2 className="mt-4 text-h2 font-semibold">{s.title}</h2>
        <p className="mt-3 max-w-2xl text-body-lg leading-relaxed text-[var(--ink-secondary)]">{s.body}</p>

        <div className="mt-6 min-h-[64px]">
          {step === 0 && (
            <a href="https://account.upstox.com/developer/apps" target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-full border border-[var(--hairline-strong)] px-5 py-2.5 text-body hover:bg-[var(--surface-3)]">
              Open the Upstox developer console ↗
            </a>
          )}
          {step === 2 && status.redirect_uri && (
            <div className="flex max-w-2xl items-center gap-2">
              <code className="flex-1 truncate rounded-[var(--radius-sm)] border border-[var(--hairline-strong)] bg-[var(--surface-2)] px-4 py-3 text-body">{status.redirect_uri}</code>
              <button onClick={() => { void navigator.clipboard?.writeText(status.redirect_uri!); setCopied(true); }}
                className="flex items-center gap-1.5 rounded-full border border-[var(--hairline-strong)] px-4 py-2.5 text-body hover:bg-[var(--surface-3)]">
                <Icon name="copy" size={15} /> {copied ? "Copied" : "Copy"}
              </button>
            </div>
          )}
          {step === 3 && <input autoFocus value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="API key" autoComplete="off" spellCheck={false} className={clsx(fieldClass, "max-w-xl")} />}
          {step === 4 && <input autoFocus type="password" value={apiSecret} onChange={(e) => setApiSecret(e.target.value)} placeholder="API secret" autoComplete="new-password" className={clsx(fieldClass, "max-w-xl")} />}
          {step === 5 && (
            <p className="text-body text-[var(--ink-muted)]">
              {status.state === "expired" ? "Your last session has ended. " : ""}Key ending ••••{status.api_key_hint} is saved.
            </p>
          )}
          {step === 6 && (
            <div className="space-y-4">
              <dl className="grid max-w-2xl grid-cols-2 gap-4 text-body">
                <div><dt className="text-small text-[var(--ink-muted)]">Account</dt><dd>{status.display_name ?? "Upstox"}</dd></div>
                <div><dt className="text-small text-[var(--ink-muted)]">Session ends</dt>
                  <dd>{status.token_expires_at ? new Date(status.token_expires_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—"}</dd></div>
                <div><dt className="text-small text-[var(--ink-muted)]">Last holdings sync</dt>
                  <dd>{status.last_successful_sync_at ? new Date(status.last_successful_sync_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "Never"}</dd></div>
                <div><dt className="text-small text-[var(--ink-muted)]">Orders</dt><dd>Paper only</dd></div>
              </dl>
              <div className="flex flex-wrap gap-3">
                <button onClick={doSync} disabled={busy} className="rounded-full bg-[var(--action)] px-5 py-2.5 text-body font-semibold text-[var(--action-ink)] disabled:opacity-60">
                  {busy ? "Syncing…" : "Sync holdings into Analysis"}
                </button>
                <button onClick={async () => { await account.upstoxDisconnect(); await onChange(); }} className="rounded-full border border-[var(--hairline-strong)] px-5 py-2.5 text-body hover:bg-[var(--surface-3)]">Disconnect</button>
                <button onClick={async () => { await account.upstoxDisconnect(true); await onChange(); }} className="rounded-full px-5 py-2.5 text-body text-[var(--down)] hover:bg-[var(--surface-3)]">Disconnect and forget key</button>
              </div>
              {sync && (
                <p className="text-body text-[var(--ink-secondary)]">
                  {sync.run.status === "success"
                    ? `Imported ${sync.run.holdings_seen} holding(s): ${sync.run.holdings_created} new, ${sync.run.holdings_updated} updated` +
                      (sync.run.details.unknown_symbols_skipped ? `, ${sync.run.details.unknown_symbols_skipped} outside the NIFTY 100 skipped.` : ".")
                    : `Sync failed: ${sync.run.error_message}`}
                </p>
              )}
            </div>
          )}
          {error && <p className="mt-3 text-body text-[var(--down)]">{error}</p>}
        </div>

        <div className="mt-10 flex items-center justify-between border-t border-[var(--hairline)] pt-8">
          <button onClick={() => { setError(null); setStep((v) => Math.max(v - 1, 0)); }} disabled={step === 0 || busy}
            className="rounded-full border border-[var(--hairline-strong)] px-6 py-3 text-body-lg disabled:opacity-30">Back</button>
          {step < 6 && (
            <button onClick={next} disabled={busy} className="rounded-full bg-[var(--action)] px-8 py-3 text-body-lg font-semibold text-[var(--action-ink)] disabled:opacity-60">
              {busy ? "Working…" : step === 4 ? "Save and continue" : step === 5 ? (status.state === "expired" ? "Log in again" : "Log in with Upstox") : "Continue"}
            </button>
          )}
        </div>
      </SettingsCard>

      <button onClick={() => setWalkthrough((v) => !v)}
        className="mt-6 flex w-full items-center justify-between rounded-[var(--radius-lg)] px-2 py-3 text-left">
        <span className="flex items-center gap-4">
          <span className="flex h-11 w-11 items-center justify-center rounded-[10px] bg-[color-mix(in_oklab,var(--down)_18%,transparent)] text-[var(--down)]"><Icon name="play" size={20} /></span>
          <span className="text-body-lg font-semibold">The whole setup at a glance</span>
        </span>
        <Icon name="chevron" size={20} className={clsx("transition-transform", walkthrough && "rotate-180")} />
      </button>
      {walkthrough && (
        <ol className="mb-2 ml-[60px] list-decimal space-y-2 text-body text-[var(--ink-secondary)]">
          {STEPS.map((st) => <li key={st.title}><span className="text-[var(--ink-primary)]">{st.title}.</span> {st.body}</li>)}
        </ol>
      )}
    </>
  );
}
