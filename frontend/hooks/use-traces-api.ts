"use client";

import { useCallback, useMemo } from "react";
import { tracesApi } from "@/lib/api";
import { usePolling } from "./use-polling";

export function useTracesApi() {
  const stats = useCallback(async () => {
    return tracesApi.stats();
  }, []);

  const sessions = useCallback(
    async (params?: { source?: string; date?: string; user_email?: string; limit?: number; offset?: number }) => {
      return tracesApi.sessions(params);
    },
    [],
  );

  const messages = useCallback(
    async (sessionId: string, params?: { limit?: number; offset?: number }) => {
      return tracesApi.messages(sessionId, params);
    },
    [],
  );

  const session = useCallback(
    async (sessionId: string) => {
      return tracesApi.session(sessionId);
    },
    [],
  );

  return useMemo(
    () => ({ stats, sessions, session, messages }),
    [stats, sessions, session, messages],
  );
}

/* ── Convenience polling hooks ── */

export function useStats(interval: number = 30000) {
  const api = useTracesApi();
  const fetcher = useCallback(() => api.stats(), [api]);
  return usePolling<Awaited<ReturnType<typeof api.stats>>>(fetcher, interval, true);
}
