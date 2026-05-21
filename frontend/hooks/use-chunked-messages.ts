"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Message } from "@/lib/types";

const CHUNK_SIZE = 500;

/**
 * Hook for incrementally loading session messages in chunks.
 *
 * - Loads CHUNK_SIZE messages initially
 * - loadMore() appends the next chunk (called on scroll-near-bottom)
 * - No aggressive polling — only fetches when asked
 */
export function useChunkedMessages(
  fetchFn: (sessionId: string, params: { limit: number; offset: number }) => Promise<Message[]>,
  sessionId: string,
  enabled: boolean,
) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);

  const offsetRef = useRef(0);
  const loadingRef = useRef(false);
  const loadedSessionRef = useRef<string | null>(null);
  const mountedRef = useRef(true);

  // Reset on session change
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Initial load when session changes
  useEffect(() => {
    if (!enabled) return;
    if (loadedSessionRef.current === sessionId) return;

    // Reset state for new session
    setMessages([]);
    setLoading(true);
    setHasMore(true);
    offsetRef.current = 0;
    loadingRef.current = true;
    loadedSessionRef.current = sessionId;

    const doFetch = async () => {
      try {
        const msgs = await fetchFn(sessionId, { limit: CHUNK_SIZE, offset: 0 });
        if (!mountedRef.current) return;
        offsetRef.current = CHUNK_SIZE;
        setMessages(msgs);
        setHasMore(msgs.length >= CHUNK_SIZE);
      } catch {
        // silent
      } finally {
        if (mountedRef.current) {
          setLoading(false);
          loadingRef.current = false;
        }
      }
    };
    doFetch();
  }, [enabled, sessionId, fetchFn]);

  // Load more — stable callback via ref, no state in deps
  const loadMore = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoadingMore(true);

    try {
      const offset = offsetRef.current;
      const msgs = await fetchFn(sessionId, { limit: CHUNK_SIZE, offset });
      if (!mountedRef.current) return;

      offsetRef.current = offset + CHUNK_SIZE;

      setMessages(prev => {
        const existingIds = new Set(prev.map(m => m.id));
        const newMsgs = msgs.filter(m => !existingIds.has(m.id));
        return [...prev, ...newMsgs];
      });
      setHasMore(msgs.length >= CHUNK_SIZE);
    } catch {
      // silent
    } finally {
      if (mountedRef.current) {
        setLoadingMore(false);
        loadingRef.current = false;
      }
    }
  }, [fetchFn, sessionId]);

  return {
    messages,
    loading,
    loadingMore,
    hasMore,
    totalLoaded: messages.length,
    loadMore,
  };
}
