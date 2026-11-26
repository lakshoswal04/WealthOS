"use client";

import { useState } from "react";
import { api, type Holding } from "@/lib/api";
import { useApi } from "@/lib/auth";
import { percent, rupees, rupeesCompact, titleCase, toneFor } from "@/lib/format";
import {
  Badge, Button, Card, CardBody, CardHeader, Empty, ErrorNote, Field,
  inputClass, LoadingRegion, SkeletonStats, SkeletonTable,
} from "@/components/ui";
import { PageHead } from "@/components/ui/shell";
import { AllocationDonut, SectorBar } from "@/components/charts";

type SortKey = "market_value" | "weight" | "unrealized_gain_pct" | "symbol";

export default function PortfolioPage() {
  const [refreshKey, setRefreshKey] = useState(0);
  const holdings = useApi(() => api.holdings(), [refreshKey]);
  const summary = useApi(() => api.portfolio(), [refreshKey]);
  const assets = useApi(() => api.assets(), []);

  const [sortKey, setSortKey] = useState<SortKey>("market_value");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ symbol: "", quantity: "", average_price: "", purchase_date: "" });
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function addHolding(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFormError(null);
    try {
      await api.addHolding({
        symbol: form.symbol.toUpperCase(),
        quantity: Number(form.quantity),
        average_price: Number(form.average_price),
        purchase_date: form.purchase_date || null,
      });
      setForm({ symbol: "", quantity: "", average_price: "", purchase_date: "" });
      setAdding(false);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setFormError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(holding: Holding) {
    if (!confirm(`Remove ${holding.symbol} from your portfolio?`)) return;
    await api.deleteHolding(holding.id);
    setRefreshKey((k) => k + 1);
  }

  if (holdings.loading) {
    return (
      <LoadingRegion label="Loading holdings">
        <SkeletonStats count={3} />
        <div className="mt-5"><SkeletonTable rows={8} columns={6} /></div>
      </LoadingRegion>
    );
  }
  if (holdings.error) return <ErrorNote message={holdings.error} />;

  const rows = [...(holdings.data ?? [])].sort((a, b) => {
    if (sortKey === "symbol") return a.symbol.localeCompare(b.symbol);
    return (Number(b[sortKey] ?? 0)) - (Number(a[sortKey] ?? 0));
  });

  return (
    <>
      <PageHead
        title="Portfolio"
        lede="Every position, priced and weighted."
        aside={<Button variant="ghost" onClick={() => setAdding((v) => !v)}>
          {adding ? "Cancel" : "Add holding"}
        </Button>}
      />

      {adding && (
        <Card className="rise mb-5">
          <CardHeader title="Add a holding"
                      subtitle="Enter the split-adjusted cost; prices here are adjusted for bonuses and splits." />
          <CardBody>
            <form onSubmit={addHolding} className="grid gap-3 sm:grid-cols-4">
              {formError && <div className="sm:col-span-4"><ErrorNote message={formError} /></div>}
              <Field label="Symbol">
                <input
                  required list="asset-symbols" className={inputClass}
                  value={form.symbol}
                  onChange={(e) => setForm({ ...form, symbol: e.target.value })}
                  placeholder="RELIANCE"
                />
                <datalist id="asset-symbols">
                  {(assets.data ?? []).map((asset) => (
                    <option key={asset.symbol} value={asset.symbol}>{asset.name}</option>
                  ))}
                </datalist>
              </Field>
              <Field label="Quantity">
                <input required type="number" step="any" min="0.0001" className={inputClass}
                       value={form.quantity}
                       onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
              </Field>
              <Field label="Average price (₹)">
                <input required type="number" step="any" min="0.01" className={inputClass}
                       value={form.average_price}
                       onChange={(e) => setForm({ ...form, average_price: e.target.value })} />
              </Field>
              <Field label="Purchase date">
                <input type="date" className={inputClass} value={form.purchase_date}
                       onChange={(e) => setForm({ ...form, purchase_date: e.target.value })} />
              </Field>
              <div className="sm:col-span-4">
                <Button type="submit" disabled={busy}>{busy ? "Adding…" : "Add to portfolio"}</Button>
              </div>
            </form>
          </CardBody>
        </Card>
      )}

      {rows.length === 0 ? (
        <Card>
          <Empty
            title="Nothing held yet"
            body="Import a CSV or add a position above to populate the dashboard."
            action={{ label: "Import holdings", href: "/import" }}
          />
        </Card>
      ) : (
        <>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card className="rise">
              <CardHeader title="By asset class" />
              <CardBody>
                {summary.data && <AllocationDonut data={summary.data.allocation_by_class} />}
              </CardBody>
            </Card>
            <Card className="rise">
              <CardHeader title="Sector exposure"
                          subtitle="Equity and ETF holdings grouped by the sector they sit in." />
              <CardBody>
                {summary.data && <SectorBar data={summary.data.allocation_by_sector} />}
              </CardBody>
            </Card>
          </div>

          <Card className="rise mt-5">
            <CardHeader
              title={`${rows.length} holdings`}
              subtitle={summary.data ? `${rupees(summary.data.total_value)} total` : undefined}
              action={
                <select
                  className="rounded-[7px] border border-[var(--hairline)] bg-[var(--surface-1)] px-2 py-1.5 text-small text-[var(--ink-secondary)]"
                  value={sortKey}
                  onChange={(e) => setSortKey(e.target.value as SortKey)}
                >
                  <option value="market_value">Sort: value</option>
                  <option value="weight">Sort: weight</option>
                  <option value="unrealized_gain_pct">Sort: gain</option>
                  <option value="symbol">Sort: symbol</option>
                </select>
              }
            />
            <div className="overflow-x-auto">
              <table className="w-full text-body">
                <caption className="sr-only">
                  Your holdings, with quantity, cost, market value and unrealised gain
                </caption>
                <thead>
                  <tr className="border-b border-[var(--hairline)] text-left text-caption uppercase tracking-[0.07em] text-[var(--ink-muted)]">
                    <th className="px-5 py-2.5 font-medium">Holding</th>
                    <th className="px-3 py-2.5 text-right font-medium">Qty</th>
                    <th className="px-3 py-2.5 text-right font-medium">Avg cost</th>
                    <th className="px-3 py-2.5 text-right font-medium">Price</th>
                    <th className="px-3 py-2.5 text-right font-medium">Value</th>
                    <th className="px-3 py-2.5 text-right font-medium">Weight</th>
                    <th className="px-3 py-2.5 text-right font-medium">Gain</th>
                    <th className="px-5 py-2.5" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((holding) => (
                    <tr key={holding.id} className="border-b border-[var(--hairline)] last:border-0 hover:bg-[var(--surface-3)]/40">
                      <td className="px-5 py-2.5">
                        <div className="font-medium text-[var(--ink-primary)]">{holding.symbol}</div>
                        <div className="flex items-center gap-1.5 text-caption text-[var(--ink-muted)]">
                          <span className="truncate">{holding.name}</span>
                          <Badge tone="neutral">{titleCase(holding.asset_class)}</Badge>
                        </div>
                      </td>
                      <td className="tabular px-3 py-2.5 text-right text-[var(--ink-secondary)]">{holding.quantity}</td>
                      <td className="tabular px-3 py-2.5 text-right text-[var(--ink-secondary)]">
                        {rupees(holding.average_price, true)}
                      </td>
                      <td className="tabular px-3 py-2.5 text-right">{rupees(holding.current_price, true)}</td>
                      <td className="tabular px-3 py-2.5 text-right">{rupeesCompact(holding.market_value)}</td>
                      <td className="tabular px-3 py-2.5 text-right text-[var(--ink-secondary)]">
                        {percent(holding.weight ?? 0, 1)}
                      </td>
                      <td className={`tabular px-3 py-2.5 text-right ${toneFor(holding.unrealized_gain_pct)}`}>
                        {percent(holding.unrealized_gain_pct ?? 0, 1, true)}
                        <div className="text-micro opacity-70">{rupeesCompact(holding.unrealized_gain)}</div>
                      </td>
                      <td className="px-5 py-2.5 text-right">
                        <button
                          onClick={() => remove(holding)}
                          className="text-caption text-[var(--ink-muted)] hover:text-[#ff8f8f]"
                          aria-label={`Remove ${holding.symbol}`}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="border-t border-[var(--hairline)] px-5 py-3 text-caption text-[var(--ink-muted)]">
              Purchase dates shown where recorded. Prices are corporate-action
              adjusted, so a cost basis entered at a pre-bonus price will
              understate your gain — the importer flags that case.
            </div>
          </Card>
        </>
      )}
    </>
  );
}
