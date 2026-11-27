"use client";

import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { Button, ErrorNote, Field, inputClass } from "@/components/ui";

export default function LoginPage() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rise">

      <h1 className="display text-[44px] leading-none">Welcome <em>back.</em></h1>
      <p className="mt-1.5 text-body text-[var(--ink-secondary)]">
        Pick up where your portfolio left off.
      </p>

      <form onSubmit={submit} className="mt-7 space-y-4">
        {error && <ErrorNote message={error} />}
        <Field label="Email">
          <input
            type="email" required autoComplete="email" className={inputClass}
            value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />
        </Field>
        <Field label="Password">
          <input
            type="password" required autoComplete="current-password" className={inputClass}
            value={password} onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
          />
        </Field>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>

      <p className="mt-6 text-small text-[var(--ink-secondary)]">
        No account yet?{" "}
        <Link href="/register" className="text-[var(--accent)] underline-offset-2 hover:underline">
          Create one
        </Link>
      </p>
    </div>
  );
}
