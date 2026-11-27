"use client";

import clsx from "clsx";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { trade, type OrderRequest, type PaperOrder } from "@/lib/trade-api";
import { inr, num, shortExpiry } from "@/lib/tfmt";
import { Modal, SourceTag } from "./primitives";
import { useSettings } from "./settings-context";

export interface TicketSpec {
  instrument: "equity" | "option";
  symbol: string;                 // stock, or the index for options
  side: "buy" | "sell";
  option_type?: "CE" | "PE" | null;
  strike?: number | null;
  expiry?: string | null;
  quantity?: number | null;       // shares, or lots for options
  lot_size?: number | null;
  ltp?: number | null;
  order_type?: "market" | "limit";
  limit_price?: number | null;
  tag?: string;
}

interface TicketContextValue { open: (spec: TicketSpec) => void; lastOrder: PaperOrder | null }

const TicketContext = createContext<TicketContextValue | null>(null);

/** Mount once near the root; any component can then open an order ticket. */
export function OrderTicketProvider({ children }: { children: ReactNode }) {
  const [spec, setSpec] = useState<TicketSpec | null>(null);
  const [lastOrder, setLastOrder] = useState<PaperOrder | null>(null);
  const open = useCallback((s: TicketSpec) => setSpec(s), []);
  const value = useMemo(() => ({ open, lastOrder }), [open, lastOrder]);
  return (
    <TicketContext.Provider value={value}>
      {children}
      {spec && (
        <OrderTicket spec={spec} onClose={() => setSpec(null)}
          onPlaced={(o) => { setLastOrder(o); window.dispatchEvent(new CustomEvent("paper-order", { detail: o })); }} />
      )}
    </TicketContext.Provider>
  );
}

export function useOrderTicket() {
  const ctx = useContext(TicketContext);
  if (!ctx) throw new Error("useOrderTicket must be used inside OrderTicketProvider");
  return ctx;
}

function displayName(spec: TicketSpec) {
  if (spec.instrument === "option") {
    return `${spec.symbol} ${spec.expiry ? shortExpiry(spec.expiry).toUpperCase() : ""} ${spec.strike ?? ""} ${spec.option_type ?? ""}`;
  }
  return spec.symbol;
}

function OrderTicket({ spec, onClose, onPlaced }: {
  spec: TicketSpec; onClose: () => void; onPlaced: (o: PaperOrder) => void;
}) {
  const { settings } = useSettings();
  const prefs = settings?.preferences;
  const [side, setSide] = useState(spec.side);
  const [qty, setQty] = useState(String(spec.quantity ?? (spec.instrument === "option" ? prefs?.default_lots : prefs?.default_quantity) ?? 1));
  const [orderType, setOrderType] = useState<"market" | "limit">(spec.order_type ?? prefs?.default_order_type ?? "market");
  const [limit, setLimit] = useState(spec.limit_price ? String(spec.limit_price) : "");
  const [product, setProduct] = useState<"delivery" | "intraday">(prefs?.default_product ?? "delivery");
  const [ltp, setLtp] = useState<number | null>(spec.ltp ?? null);
  const [source, setSource] = useState<string | null>(spec.instrument === "option" ? "live" : null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PaperOrder | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [lotSize, setLotSize] = useState<number | null>(spec.lot_size ?? null);
  useEffect(() => {
    if (spec.instrument === "equity") {
      trade.quote(spec.symbol).then((q) => { setLtp(q.ltp); setSource(q.source); }).catch(() => {});
    } else if (!spec.lot_size) {
      // The real lot size, from the exchange's instrument list.
      trade.expiries(spec.symbol).then((r) => setLotSize(r.lot_size)).catch(() => {});
    }
  }, [spec]);

  const isOption = spec.instrument === "option";
  const lot = lotSize ?? 1;
  const n = Math.max(0, Math.floor(Number(qty) || 0));
  const units = isOption ? n * lot : n;
  const price = orderType === "limit" && Number(limit) > 0 ? Number(limit) : ltp;
  const value = price ? price * units : null;

  async function submit() {
    setBusy(true); setError(null); setResult(null);
    const order: OrderRequest = {
      instrument: spec.instrument, symbol: spec.symbol, side, order_type: orderType,
      limit_price: orderType === "limit" ? Number(limit) : null,
      tag: spec.tag ?? "manual",
      ...(isOption
        ? { lots: n, option_type: spec.option_type, strike: spec.strike, expiry: spec.expiry }
        : { quantity: n, product }),
    };
    try {
      const placed = await trade.placeOrder(order);
      setResult(placed);
      onPlaced(placed);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open onClose={onClose} title={
      <span className="flex items-center gap-2">
        <span className={clsx("rounded-full px-2 py-0.5 text-caption font-semibold uppercase",
          side === "buy" ? "bg-[var(--buy)] text-white" : "bg-[var(--sell)] text-white")}>{side}</span>
        <span className="tabular">{displayName(spec)}</span>
      </span>
    }>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <div className="text-micro uppercase tracking-[0.12em] text-[var(--ink-muted)]">Last price</div>
          <div className="tabular text-h3">{ltp !== null ? inr(ltp) : "—"}</div>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <SourceTag source={source} />
          <span className="rounded-full border border-[var(--hairline-strong)] px-2 py-[1px] text-micro text-[var(--ink-muted)]">Paper trade</span>
        </div>
      </div>

      <div className="mb-3 grid grid-cols-2 gap-2">
        {(["buy", "sell"] as const).map((s) => (
          <button key={s} onClick={() => setSide(s)}
            className={clsx("rounded-full py-2 text-body font-semibold capitalize transition-colors",
              side === s ? (s === "buy" ? "bg-[var(--buy)] text-white" : "bg-[var(--sell)] text-white")
                : "border border-[var(--hairline-strong)] text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]")}>
            {s}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="mb-1 block text-caption text-[var(--ink-muted)]">{isOption ? `Lots (×${lot})` : "Quantity"}</span>
          <input value={qty} onChange={(e) => setQty(e.target.value.replace(/[^\d]/g, ""))} inputMode="numeric"
            className="tabular w-full rounded-[var(--radius-sm)] border border-[var(--hairline-strong)] bg-[var(--surface-2)] px-3 py-2 text-body focus:border-[var(--ink-muted)] focus:outline-none" />
        </label>
        <label className="block">
          <span className="mb-1 block text-caption text-[var(--ink-muted)]">Order type</span>
          <select value={orderType} onChange={(e) => setOrderType(e.target.value as "market" | "limit")}
            className="w-full rounded-[var(--radius-sm)] border border-[var(--hairline-strong)] bg-[var(--surface-2)] px-3 py-2 text-body focus:outline-none">
            <option value="market">Market</option>
            <option value="limit">Limit</option>
          </select>
        </label>
        {orderType === "limit" && (
          <label className="col-span-2 block">
            <span className="mb-1 block text-caption text-[var(--ink-muted)]">Limit price</span>
            <input value={limit} onChange={(e) => setLimit(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal"
              placeholder={ltp ? num(ltp) : ""}
              className="tabular w-full rounded-[var(--radius-sm)] border border-[var(--hairline-strong)] bg-[var(--surface-2)] px-3 py-2 text-body focus:outline-none" />
          </label>
        )}
        {!isOption && (
          <div className="col-span-2 flex gap-2">
            {(["delivery", "intraday"] as const).map((p) => (
              <button key={p} onClick={() => setProduct(p)}
                className={clsx("rounded-full border px-3 py-1 text-small capitalize",
                  product === p ? "border-[var(--ink-secondary)] text-[var(--ink-primary)]" : "border-[var(--hairline-strong)] text-[var(--ink-muted)]")}>
                {p}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-[var(--hairline)] pt-3 text-small">
        <span className="text-[var(--ink-muted)]">{isOption ? `${units} units · ` : ""}Approx. value</span>
        <span className="tabular text-body-lg">{value !== null ? inr(value) : "—"}</span>
      </div>

      {error && <p className="mt-3 rounded-[var(--radius-sm)] bg-[color-mix(in_oklab,var(--down)_12%,transparent)] px-3 py-2 text-small text-[var(--down)]">{error}</p>}
      {result && (
        <p className={clsx("mt-3 rounded-[var(--radius-sm)] px-3 py-2 text-small",
          result.status === "filled" ? "bg-[color-mix(in_oklab,var(--up)_12%,transparent)] text-[var(--up)]"
            : result.status === "open" ? "bg-[var(--surface-3)] text-[var(--ink-secondary)]"
              : "bg-[color-mix(in_oklab,var(--down)_12%,transparent)] text-[var(--down)]")}>
          {result.status === "filled" && `Filled ${result.quantity} at ${inr(result.fill_price)}.`}
          {result.status === "open" && `Limit order resting at ${inr(result.limit_price)}.`}
          {result.status === "rejected" && `Rejected: ${result.reject_reason}`}
        </p>
      )}

      <button onClick={result ? onClose : submit} disabled={busy || (!result && (n <= 0 || (orderType === "limit" && !(Number(limit) > 0))))}
        className={clsx("mt-4 w-full rounded-full py-2.5 text-body font-semibold text-white transition-opacity disabled:opacity-50",
          result ? "bg-[var(--surface-4)]" : side === "buy" ? "bg-[var(--buy)] hover:opacity-90" : "bg-[var(--sell)] hover:opacity-90")}>
        {result ? "Done" : busy ? "Placing…" : `${side === "buy" ? "Buy" : "Sell"} ${n || ""} ${isOption ? (n === 1 ? "lot" : "lots") : ""}`.trim()}
      </button>
      <p className="mt-2.5 text-center text-micro text-[var(--ink-faint)]">
        Paper trading at real prices. No order is sent to any exchange or broker.
      </p>
    </Modal>
  );
}
