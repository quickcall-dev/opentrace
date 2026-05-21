"use client";

import { useEffect, useRef, useState } from "react";

export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number = 2000,
  enabled: boolean = true,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [isStale, setIsStale] = useState(false);
  const mountedRef = useRef(true);
  const consecutiveErrorsRef = useRef(0);
  const pausedUntilRef = useRef(0);
  const hasDataRef = useRef(false);

  useEffect(() => {
    if (!enabled) return;

    mountedRef.current = true;
    consecutiveErrorsRef.current = 0;
    pausedUntilRef.current = 0;

    const poll = async () => {
      // Circuit breaker: skip if paused
      if (pausedUntilRef.current > Date.now()) return;
      // Pause polling when tab is hidden
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;

      try {
        const result = await fetcher();
        if (mountedRef.current) {
          setData(result);
          setError(null);
          setIsStale(false);
          setLoading(false);
          hasDataRef.current = true;
          consecutiveErrorsRef.current = 0;
          pausedUntilRef.current = 0;
        }
      } catch (e) {
        if (!mountedRef.current) return;

        const msg = e instanceof Error ? e.message : String(e);
        setLoading(false);

        if (hasDataRef.current) {
          // Keep showing stale data, just mark as stale
          setIsStale(true);
        } else {
          // No data yet — show error
          setError(msg);
        }

        consecutiveErrorsRef.current++;
        const count = consecutiveErrorsRef.current;

        if (msg.includes("401")) {
          pausedUntilRef.current = Date.now() + Math.min(count * 5000, 30000);
        } else {
          pausedUntilRef.current =
            Date.now() + Math.min(2000 * Math.pow(2, count - 1), 30000);
        }
      }
    };

    poll();
    const id = setInterval(poll, intervalMs);

    return () => {
      mountedRef.current = false;
      clearInterval(id);
    };
  }, [fetcher, intervalMs, enabled]);

  return { data, error, loading, isStale };
}
