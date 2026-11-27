"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { unavailableFrom, type Unavailable } from "@/lib/clients/http";

/**
 * Load an endpoint and keep it fresh.
 *
 * Polling pauses while the tab is hidden: a background tab hammering the
 * API every few seconds is wasted work on both ends. The previous value is
 * kept on screen while a refresh is in flight, so tickers update in place
 * instead of flashing to a spinner.
 */
export function usePoll<T>(loader: () => Promise<T>, intervalMs: number | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [failure, setFailure] = useState<Unavailable | null>(null);
  const [loading, setLoading] = useState(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const load = useCallback(async () => {
    try {
      const next = await loaderRef.current();
      setData(next);
      setError(null);
      setFailure(null);
    } catch (err) {
      setError((err as Error).message);
      setFailure(unavailableFrom(err));
      // Stale data must not sit beside a "now unavailable" message.
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setData(null);
    void load();
    if (!intervalMs) return () => { cancelled = true; };
    const id = window.setInterval(() => {
      if (!cancelled && document.visibilityState === "visible") void load();
    }, intervalMs);
    return () => { cancelled = true; window.clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, ...deps]);

  return { data, error, failure, loading, reload: load, setData };
}

/** Close a popover on outside click or Escape. */
export function useDismiss(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);
  return ref;
}
