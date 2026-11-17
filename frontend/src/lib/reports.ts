/**
 * Safe access into the pipeline reports.
 *
 * The reports are JSON written by Python and deliberately typed loosely on
 * the client: mirroring every nested field in TypeScript would be a standing
 * maintenance cost that buys no real safety, since the shape is owned by the
 * pipelines rather than by this app.
 *
 * What does matter is that a page never crashes because a stage has not been
 * run. These helpers walk a dotted path and return a typed fallback, so a
 * missing report degrades to a stated default instead of a white screen.
 */

import type { Report } from "@/lib/api";

type Source = Report | Record<string, unknown> | undefined | null;

function walk(source: Source, path: string): unknown {
  if (!source) return undefined;
  let node: unknown = source;
  for (const key of path.split(".")) {
    if (node === null || typeof node !== "object") return undefined;
    node = (node as Record<string, unknown>)[key];
  }
  return node;
}

export function num(source: Source, path: string, fallback = 0): number {
  const value = walk(source, path);
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/** For a value that is genuinely absent rather than zero — a missing score
 *  and a score of zero must not render the same way. */
export function maybeNum(source: Source, path: string): number | null {
  const value = walk(source, path);
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function str(source: Source, path: string, fallback = ""): string {
  const value = walk(source, path);
  return typeof value === "string" ? value : fallback;
}

export function bool(source: Source, path: string, fallback = false): boolean {
  const value = walk(source, path);
  return typeof value === "boolean" ? value : fallback;
}

export function list<T = unknown>(source: Source, path: string): T[] {
  const value = walk(source, path);
  return Array.isArray(value) ? (value as T[]) : [];
}

export function record(source: Source, path: string): Record<string, unknown> {
  const value = walk(source, path);
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** A record of numbers, for the many `{name: score}` shapes in the reports. */
export function numberRecord(source: Source, path: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [key, value] of Object.entries(record(source, path))) {
    if (typeof value === "number" && Number.isFinite(value)) out[key] = value;
  }
  return out;
}

export function isAvailable(report: Source): boolean {
  return bool(report, "available", false);
}

export function reasonFor(report: Source): string {
  return str(report, "reason", "This report has not been generated yet.");
}
