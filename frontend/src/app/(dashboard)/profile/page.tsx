"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApi, useAuth } from "@/lib/auth";
import { rupees, shortDate, titleCase } from "@/lib/format";
import {
  Badge, Button, Card, CardBody, CardHeader, ErrorNote, Field, inputClass, Spinner, Stat,
} from "@/components/ui";
import { PageHead } from "@/components/ui/shell";

const RISK_BANDS: Record<string, string> = {
  conservative: "4% to 10% annualised volatility",
  moderate: "8% to 17% annualised volatility",
  aggressive: "14% to 28% annualised volatility",
};

export default function ProfilePage() {
  const { user, refresh } = useAuth();
  const models = useApi(() => api.modelStatus(), []);
  const [form, setForm] = useState({
    full_name: "", age: "", annual_income: "",
    monthly_savings: "", risk_tolerance: "moderate", investment_horizon_years: "",
  });
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!user) return;
    setForm({
      full_name: user.full_name ?? "",
      age: user.age?.toString() ?? "",
      annual_income: user.annual_income?.toString() ?? "",
      monthly_savings: user.monthly_savings?.toString() ?? "",
      risk_tolerance: user.risk_tolerance ?? "moderate",
      investment_horizon_years: user.investment_horizon_years?.toString() ?? "",
    });
  }, [user]);

  if (!user) return <Spinner />;

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const payload: Record<string, unknown> = { risk_tolerance: form.risk_tolerance };
      payload.full_name = form.full_name || null;
      if (form.age) payload.age = Number(form.age);
      if (form.annual_income) payload.annual_income = Number(form.annual_income);
      if (form.monthly_savings) payload.monthly_savings = Number(form.monthly_savings);
      if (form.investment_horizon_years) {
        payload.investment_horizon_years = Number(form.investment_horizon_years);
      }
      await api.updateProfile(payload);
      await refresh();
      setSaved(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const set = (key: string) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>,
  ) => { setForm((prev) => ({ ...prev, [key]: e.target.value })); setSaved(false); };

  return (
    <>
      <PageHead
        title="Profile"
        lede="These details drive the risk band your portfolio is scored against and the contributions used in goal projections."
      />

      <div className="grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
        <Card className="rise">
          <CardHeader title="Investor details" />
          <CardBody>
            <form onSubmit={save} className="grid gap-4 sm:grid-cols-2">
              {error && <div className="sm:col-span-2"><ErrorNote message={error} /></div>}

              <div className="sm:col-span-2">
                <Field label="Full name">
                  <input className={inputClass} value={form.full_name} onChange={set("full_name")} />
                </Field>
              </div>
              <Field label="Age">
                <input type="number" min={18} max={100} className={inputClass}
                       value={form.age} onChange={set("age")} />
              </Field>
              <Field label="Investment horizon (years)">
                <input type="number" min={1} max={60} className={inputClass}
                       value={form.investment_horizon_years}
                       onChange={set("investment_horizon_years")} />
              </Field>
              <Field label="Annual income (₹)">
                <input type="number" min={0} className={inputClass}
                       value={form.annual_income} onChange={set("annual_income")} />
              </Field>
              <Field label="Monthly savings (₹)"
                     hint="Used as the default contribution for goals that set none.">
                <input type="number" min={0} className={inputClass}
                       value={form.monthly_savings} onChange={set("monthly_savings")} />
              </Field>

              <div className="sm:col-span-2">
                <Field label="Risk tolerance"
                       hint={`Scored against ${RISK_BANDS[form.risk_tolerance] ?? ""}. Exceeding your band costs more than falling short of it.`}>
                  <select className={inputClass} value={form.risk_tolerance} onChange={set("risk_tolerance")}>
                    <option value="conservative">Conservative</option>
                    <option value="moderate">Moderate</option>
                    <option value="aggressive">Aggressive</option>
                  </select>
                </Field>
              </div>

              <div className="flex items-center gap-3 sm:col-span-2">
                <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save changes"}</Button>
                {saved && <span className="text-[12.5px] text-[var(--good)]">Saved.</span>}
              </div>
            </form>
          </CardBody>
        </Card>

        <div className="space-y-5">
          <Card className="rise">
            <CardHeader title="Account" />
            <CardBody className="space-y-4">
              <Stat label="Email" value={<span className="text-[15px]">{user.email}</span>} />
              <Stat label="Joined" value={<span className="text-[15px]">{shortDate(user.joined_on ?? user.created_at)}</span>} />
              <Stat label="Risk tolerance"
                    value={<span className="text-[15px]">{titleCase(user.risk_tolerance ?? "not set")}</span>}
                    sub={RISK_BANDS[user.risk_tolerance ?? ""] ?? undefined} />
              {user.monthly_savings != null && (
                <Stat label="Monthly savings"
                      value={<span className="text-[15px]">{rupees(user.monthly_savings)}</span>} />
              )}
            </CardBody>
          </Card>

          <Card className="rise">
            <CardHeader
              title="Model status"
              subtitle="Which trained artifacts the server loaded. A missing one disables its panel rather than breaking the app."
            />
            <CardBody>
              {models.loading && <Spinner />}
              {models.data && (
                <ul className="space-y-2">
                  {Object.entries(models.data.available).map(([name, loaded]) => (
                    <li key={name} className="flex items-center justify-between gap-3">
                      <span className="text-[12.5px] text-[var(--ink-secondary)]">{titleCase(name)}</span>
                      <Badge tone={loaded ? "good" : "warning"}>
                        {loaded ? "loaded" : "unavailable"}
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  );
}
