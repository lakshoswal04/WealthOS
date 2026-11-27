"use client";

import Link from "next/link";
import { useState } from "react";
import { SettingsCard, SettingsFrame, fieldClass } from "@/components/settings/frame";
import { useAuth } from "@/lib/auth";
import { account } from "@/lib/trade-api";

export default function AccountPage() {
  const { user, signOut } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [delPw, setDelPw] = useState("");
  const [delErr, setDelErr] = useState<string | null>(null);

  async function changePassword() {
    setPwMsg(null);
    if (next.length < 8) { setPwMsg({ ok: false, text: "The new password needs at least 8 characters." }); return; }
    try { await account.changePassword(current, next); setPwMsg({ ok: true, text: "Password changed." }); setCurrent(""); setNext(""); }
    catch (err) { setPwMsg({ ok: false, text: (err as Error).message }); }
  }
  async function remove() {
    setDelErr(null);
    try { await account.deleteAccount(delPw); signOut(); }
    catch (err) { setDelErr((err as Error).message); }
  }

  return (
    <SettingsFrame title="Account">
      <SettingsCard className="flex flex-wrap items-center justify-between gap-4 px-8 py-6">
        <div>
          <div className="text-h3 font-semibold">{user?.full_name || user?.email.split("@")[0]}</div>
          <div className="mt-1 text-body text-[var(--ink-muted)]">{user?.email}</div>
        </div>
        <Link href="/profile" className="rounded-full border border-[var(--hairline-strong)] px-5 py-2.5 text-body hover:bg-[var(--surface-3)]">Edit investor profile</Link>
      </SettingsCard>

      <h2 className="mb-4 mt-10 text-h3 font-semibold">Password</h2>
      <SettingsCard className="space-y-4 px-8 py-6">
        <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} placeholder="Current password" className={fieldClass} />
        <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} placeholder="New password (8+ characters)" className={fieldClass} />
        <div className="flex items-center gap-4">
          <button onClick={changePassword} disabled={!current || !next} className="rounded-full bg-[var(--action)] px-6 py-2.5 text-body font-semibold text-[var(--action-ink)] disabled:opacity-50">Change password</button>
          {pwMsg && <span className={pwMsg.ok ? "text-body text-[var(--up)]" : "text-body text-[var(--down)]"}>{pwMsg.text}</span>}
        </div>
      </SettingsCard>

      <h2 className="mb-4 mt-10 text-h3 font-semibold text-[var(--down)]">Delete account</h2>
      <SettingsCard className="px-8 py-6">
        <p className="text-body text-[var(--ink-secondary)]">
          Deletes your account and everything in it: paper trades, holdings, goals, chats, memory and broker connection. This cannot be undone.
        </p>
        {!confirming ? (
          <button onClick={() => setConfirming(true)} className="mt-4 rounded-full border border-[color-mix(in_oklab,var(--down)_50%,transparent)] px-6 py-2.5 text-body text-[var(--down)] hover:bg-[color-mix(in_oklab,var(--down)_10%,transparent)]">
            Delete my account
          </button>
        ) : (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <input type="password" autoFocus value={delPw} onChange={(e) => setDelPw(e.target.value)} placeholder="Confirm with your password" className={`${fieldClass} max-w-sm`} />
            <button onClick={remove} disabled={!delPw} className="rounded-full bg-[var(--sell)] px-6 py-3 text-body font-semibold text-white disabled:opacity-50">Delete permanently</button>
            <button onClick={() => { setConfirming(false); setDelPw(""); }} className="rounded-full px-4 py-3 text-body text-[var(--ink-secondary)]">Keep my account</button>
            {delErr && <span className="w-full text-body text-[var(--down)]">{delErr}</span>}
          </div>
        )}
      </SettingsCard>
    </SettingsFrame>
  );
}
