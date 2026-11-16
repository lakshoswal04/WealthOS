/** Display formatting. Indian numbering throughout, since the universe,
 *  prices and investors are all Indian. */

const INR = new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", maximumFractionDigits: 0,
});
const INR_PRECISE = new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", maximumFractionDigits: 2,
});

export function rupees(value: number | null | undefined, precise = false): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return (precise ? INR_PRECISE : INR).format(value);
}

/** Lakh and crore are how Indian investors actually read large amounts. */
export function rupeesCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const sign = value < 0 ? "-" : "";
  const n = Math.abs(value);
  if (n >= 1e7) return `${sign}₹${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `${sign}₹${(n / 1e5).toFixed(2)} L`;
  if (n >= 1e3) return `${sign}₹${(n / 1e3).toFixed(1)}k`;
  return `${sign}₹${n.toFixed(0)}`;
}

export function percent(value: number | null | undefined, digits = 2, signed = false): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const formatted = `${(value * 100).toFixed(digits)}%`;
  return signed && value > 0 ? `+${formatted}` : formatted;
}

/** For values the API already expresses as percentage points. */
export function percentPoints(value: number | null | undefined, digits = 2, signed = false): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const formatted = `${value.toFixed(digits)}%`;
  return signed && value > 0 ? `+${formatted}` : formatted;
}

export function ratio(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

export function shortDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function monthLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
}

export function titleCase(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Gains are green and losses red, but never colour alone: callers pair this
 *  with an explicit sign in the text. */
export function toneFor(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "text-[var(--ink-muted)]";
  if (value > 0) return "text-[var(--good)]";
  if (value < 0) return "text-[var(--critical)]";
  return "text-[var(--ink-secondary)]";
}
