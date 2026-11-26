"use client";

import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { Button, ErrorNote, Field, inputClass } from "@/components/ui";

export default function RegisterPage() {
  const { signUp } = useAuth();
  const [form, setForm] = useState({
    email: "", password: "", full_name: "",
    age: "", annual_income: "", monthly_savings: "",
    risk_tolerance: "moderate", investment_horizon_years: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (key: string) => (
    event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>,
  ) => setForm((prev) => ({ ...prev, [key]: event.target.value }));

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // Blank optional fields are omitted rather than sent as empty strings,
      // which the API would reject.
      const payload: Record<string, unknown> = {
        email: form.email, password: form.password,
      };
      if (form.full_name) payload.full_name = form.full_name;
      if (form.age) payload.age = Number(form.age);
      if (form.annual_income) payload.annual_income = Number(form.annual_income);
      if (form.monthly_savings) payload.monthly_savings = Number(form.monthly_savings);
      if (form.risk_tolerance) payload.risk_tolerance = form.risk_tolerance;
      if (form.investment_horizon_years) {
        payload.investment_horizon_years = Number(form.investment_horizon_years);
      }
      await signUp(payload);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rise">
      <h1 className="display text-h1 leading-tight">Create your account</h1>
      <p className="mt-1.5 text-body text-[var(--ink-secondary)]">
        Your profile shapes the risk bands and goal projections, so it is worth
        filling in.
      </p>

      <form onSubmit={submit} className="mt-6 space-y-4">
        {error && <ErrorNote message={error} />}

        <Field label="Email">
          <input type="email" required autoComplete="email" className={inputClass}
                 value={form.email} onChange={set("email")} placeholder="you@example.com" />
        </Field>
        <Field label="Password" hint="At least 8 characters.">
          <input type="password" required minLength={8} autoComplete="new-password"
                 className={inputClass} value={form.password} onChange={set("password")} />
        </Field>
        <Field label="Full name">
          <input className={inputClass} value={form.full_name} onChange={set("full_name")} />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Age">
            <input type="number" min={18} max={100} className={inputClass}
                   value={form.age} onChange={set("age")} placeholder="32" />
          </Field>
          <Field label="Horizon (years)">
            <input type="number" min={1} max={60} className={inputClass}
                   value={form.investment_horizon_years}
                   onChange={set("investment_horizon_years")} placeholder="20" />
          </Field>
          <Field label="Annual income (₹)">
            <input type="number" min={0} className={inputClass}
                   value={form.annual_income} onChange={set("annual_income")} placeholder="1800000" />
          </Field>
          <Field label="Monthly savings (₹)">
            <input type="number" min={0} className={inputClass}
                   value={form.monthly_savings} onChange={set("monthly_savings")} placeholder="45000" />
          </Field>
        </div>

        <Field label="Risk tolerance" hint="Sets the volatility band your portfolio is scored against.">
          <select className={inputClass} value={form.risk_tolerance} onChange={set("risk_tolerance")}>
            <option value="conservative">Conservative — 4% to 10% volatility</option>
            <option value="moderate">Moderate — 8% to 17% volatility</option>
            <option value="aggressive">Aggressive — 14% to 28% volatility</option>
          </select>
        </Field>

        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Creating…" : "Create account"}
        </Button>
      </form>

      <p className="mt-6 text-small text-[var(--ink-secondary)]">
        Already registered?{" "}
        <Link href="/login" className="text-[var(--accent)] underline-offset-2 hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
