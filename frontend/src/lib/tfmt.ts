/** Number formats for the trading surfaces. Indian grouping throughout. */

const GROUPED = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const WHOLE = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export const num = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined || !Number.isFinite(v) ? "—"
    : digits === 2 ? GROUPED.format(v) : v.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const whole = (v: number | null | undefined) =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : WHOLE.format(v);

export const inr = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined || !Number.isFinite(v) ? "—"
    : `${v < 0 ? "-" : ""}₹${num(Math.abs(v), digits)}`;

/** Signed rupee change: "+₹784" / "-₹7,556". */
export const inrSigned = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined || !Number.isFinite(v) ? "—"
    : `${v > 0 ? "+" : v < 0 ? "-" : ""}₹${num(Math.abs(v), digits)}`;

export const pct = (v: number | null | undefined, digits = 2, signed = true) =>
  v === null || v === undefined || !Number.isFinite(v) ? "—"
    : `${signed && v > 0 ? "+" : ""}${v.toFixed(digits)}%`;

export const signed = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined || !Number.isFinite(v) ? "—"
    : `${v > 0 ? "+" : ""}${num(v, digits)}`;

/** Open interest in lakh or crore, as Indian option traders read it. */
export const oiShort = (v: number | null | undefined) => {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const a = Math.abs(v), s = v < 0 ? "-" : "";
  if (a >= 1e7) return `${s}${(a / 1e7).toFixed(2)}Cr`;
  if (a >= 1e5) return `${s}${(a / 1e5).toFixed(2)}L`;
  if (a >= 1e3) return `${s}${(a / 1e3).toFixed(1)}K`;
  return `${s}${a.toFixed(0)}`;
};

export const tone = (v: number | null | undefined) =>
  v === null || v === undefined || v === 0 ? "text-[var(--ink-secondary)]"
    : v > 0 ? "text-[var(--up)]" : "text-[var(--down)]";

export const shortExpiry = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
