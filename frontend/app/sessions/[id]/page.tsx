"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useTracesApi } from "@/hooks/use-traces-api";
import { useTracesContext } from "@/context/traces-context";
import { usePolling } from "@/hooks/use-polling";
import { useChunkedMessages } from "@/hooks/use-chunked-messages";
import { SessionSidebar, SessionFilterToolbar, type LoadMoreFn, type SidebarFilters, type GanttClickInfo } from "@/components/session-sidebar";
import { ParallelSessionView, type ParallelViewData } from "@/components/parallel-session-view";
import { SessionHeaderBar } from "@/components/session-header-bar";
import { RichMessage } from "@/components/rich-message";
import { CompactionBreak, InterruptionBreak } from "@/components/breakpoints";
import { Minimap } from "@/components/minimap";
import { JumpBar } from "@/components/jump-bar";
import { Skeleton } from "@/components/ui/skeleton";

import {
  isCompaction,
  isInterruption,
  filterVisibleMessages,
} from "@/lib/session-utils";
import type { Session, Message } from "@/lib/types";

export default function SessionDetailPage() {
  const params = useParams<{ id: string }>();
  const paramSessionId = decodeURIComponent(params.id ?? "");
  const [sessionId, setSessionId] = useState(paramSessionId);
  const api = useTracesApi();
  const { isReady, canSeeTeamData } = useTracesContext();
  const searchParams = useSearchParams();

  // Sync if URL param changes (e.g. browser back/forward)
  useEffect(() => { setSessionId(paramSessionId); }, [paramSessionId]);
  const scrollRef = useRef<HTMLDivElement>(null);

  const [currentPrompt, setCurrentPrompt] = useState(1);
  const promptIndexRef = useRef(0);

  // Parallel session view state
  const [parallelData, setParallelData] = useState<ParallelViewData | null>(null);
  const [parallelMessages, setParallelMessages] = useState<Record<string, Message[]>>({});
  const [parallelLoading, setParallelLoading] = useState(false);

  // Sidebar filters — start empty (SSR-safe), then sync from URL after mount
  const [filters, setFiltersState] = useState<SidebarFilters>({
    developers: [],
    sources: [],
    date: undefined,
  });

  // Hydrate filters from URL search params after mount
  const filtersHydrated = useRef(false);
  useEffect(() => {
    if (filtersHydrated.current) return;
    filtersHydrated.current = true;
    const devs = searchParams.get("dev")?.split(",").filter(Boolean) ?? [];
    const srcs = searchParams.get("src")?.split(",").filter(Boolean) ?? [];
    const date = searchParams.get("date") || undefined;
    if (devs.length || srcs.length || date) {
      setFiltersState({ developers: devs, sources: srcs, date });
    }
  }, [searchParams]);

  const setFilters = useCallback((f: SidebarFilters) => {
    setFiltersState(f);
    const q = new URLSearchParams();
    if (f.developers.length) q.set("dev", f.developers.join(","));
    if (f.sources.length) q.set("src", f.sources.join(","));
    if (f.date) q.set("date", f.date);
    const qs = q.toString();
    window.history.replaceState(null, "", `/sessions/${encodeURIComponent(sessionId)}${qs ? "?" + qs : ""}`);
  }, [sessionId]);

  // Stable serialized keys for array deps
  const devsKey = filters.developers.slice().sort().join(",");
  const srcsKey = filters.sources.slice().sort().join(",");

  // Paginated sessions for sidebar
  const SIDEBAR_PAGE = 30;
  const [sidebarSessions, setSidebarSessions] = useState<Session[]>([]);
  const [sidebarOffset, setSidebarOffset] = useState(0);
  const [sidebarHasMore, setSidebarHasMore] = useState(true);
  const [sessionsLoading, setSessionsLoading] = useState(true);

  // Stable ref for api.sessions to avoid effect loops
  const apiRef = useRef(api);
  apiRef.current = api;

  // Initial load + reload on filter change
  useEffect(() => {
    if (!isReady) return;
    let cancelled = false;
    setSessionsLoading(true);
    setSidebarOffset(0);

    const devs = devsKey ? devsKey.split(",") : [];
    const srcs = srcsKey ? srcsKey.split(",") : [];

    // API supports single value — use it for single selection, otherwise fetch broader and filter client-side
    const apiDev = devs.length === 1 ? devs[0] : undefined;
    const apiSrc = srcs.length === 1 ? srcs[0] : undefined;
    apiRef.current
      .sessions({ limit: SIDEBAR_PAGE * 3, offset: 0, user_email: apiDev, source: apiSrc, date: filters.date })
      .then((data) => {
        if (cancelled) return;
        // Client-side filter for multi-select
        let filtered = data;
        if (devs.length > 0) {
          const devSet = new Set(devs);
          filtered = filtered.filter((s) => s.user_email && devSet.has(s.user_email));
        }
        if (srcs.length > 0) {
          const srcSet = new Set(srcs);
          filtered = filtered.filter((s) => srcSet.has(s.source));
        }
        setSidebarSessions(filtered);
        setSidebarOffset(SIDEBAR_PAGE * 3);
        setSidebarHasMore(data.length >= SIDEBAR_PAGE * 3);
        setSessionsLoading(false);
        if (filtered.length > 0 && !filtered.some((s) => s.id === sessionId)) {
          const q = new URLSearchParams();
          if (devs.length) q.set("dev", devs.join(","));
          if (srcs.length) q.set("src", srcs.join(","));
          if (filters.date) q.set("date", filters.date);
          const qs = q.toString();
          setSessionId(filtered[0].id);
          window.history.replaceState(null, "", `/sessions/${encodeURIComponent(filtered[0].id)}${qs ? "?" + qs : ""}`);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          console.error("[sessions] fetch failed:", err);
          setSessionsLoading(false);
        }
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [devsKey, srcsKey, filters.date, isReady]);

  // Load more callback for sidebar
  const loadMoreSessions: LoadMoreFn = useCallback(async () => {
    const data = await apiRef.current.sessions({
      limit: SIDEBAR_PAGE,
      offset: sidebarOffset,
      user_email: filters.developers.length === 1 ? filters.developers[0] : undefined,
      source: filters.sources.length === 1 ? filters.sources[0] : undefined,
      date: filters.date,
    });
    let filtered = data;
    if (filters.developers.length > 0) {
      const devSet = new Set(filters.developers);
      filtered = filtered.filter((s) => s.user_email && devSet.has(s.user_email));
    }
    if (filters.sources.length > 0) {
      const srcSet = new Set(filters.sources);
      filtered = filtered.filter((s) => srcSet.has(s.source));
    }
    setSidebarSessions((prev) => {
      const ids = new Set(prev.map((s) => s.id));
      return [...prev, ...filtered.filter((s) => !ids.has(s.id))];
    });
    setSidebarOffset((prev) => prev + SIDEBAR_PAGE);
    setSidebarHasMore(data.length >= SIDEBAR_PAGE);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sidebarOffset, devsKey, srcsKey, filters.date]);

  // Fetch active session
  const sessionFetcher = useCallback(
    () => api.session(sessionId),
    [api.session, sessionId],
  );
  const { data: session } = usePolling<Session>(sessionFetcher, 10000, isReady);

  // Fetch messages in chunks (500 at a time, load more on scroll)
  const messageFetchFn = useCallback(
    (sid: string, params: { limit: number; offset: number }) =>
      api.messages(sid, params),
    [api.messages],
  );
  const {
    messages,
    loading: messagesLoading,
    loadingMore: messagesLoadingMore,
    hasMore: messagesHasMore,
    loadMore: loadMoreMessages,
  } = useChunkedMessages(messageFetchFn, sessionId, isReady);

  const visibleMessages = useMemo(
    () => filterVisibleMessages(messages ?? []),
    [messages],
  );

  // User prompt indices for jump navigation
  const userPromptIndices = useMemo(
    () =>
      visibleMessages.reduce<number[]>((acc, m, i) => {
        if (m.msg_type === "user" && !isCompaction(m)) acc.push(i);
        return acc;
      }, []),
    [visibleMessages],
  );

  // Navigate to different session — use shallow navigation to avoid full page refresh
  const handleSelectSession = useCallback(
    (id: string) => {
      const q = new URLSearchParams();
      if (filters.developers.length) q.set("dev", filters.developers.join(","));
      if (filters.sources.length) q.set("src", filters.sources.join(","));
      if (filters.date) q.set("date", filters.date);
      const qs = q.toString();
      setSessionId(id);
      window.history.pushState(null, "", `/sessions/${encodeURIComponent(id)}${qs ? "?" + qs : ""}`);
    },
    [filters],
  );

  // Helper: get user prompt DOM elements by data-msg-seq
  const getUserPromptEls = useCallback(() => {
    const panel = scrollRef.current;
    if (!panel) return [];
    return userPromptIndices
      .map((seqIdx) => panel.querySelector<HTMLElement>(`[data-msg-seq="${seqIdx}"]`))
      .filter(Boolean) as HTMLElement[];
  }, [userPromptIndices]);

  // Jump between user prompts — uses ref for immediate sequential clicks
  const jumpToPrompt = useCallback(
    (dir: number) => {
      const userEls = getUserPromptEls();
      if (userEls.length === 0) return;

      const next = Math.max(0, Math.min(userEls.length - 1, promptIndexRef.current + dir));
      promptIndexRef.current = next;
      setCurrentPrompt(next + 1);

      // Use instant scroll so repeated clicks always work
      userEls[next].scrollIntoView({ behavior: "instant", block: "start" });
    },
    [getUserPromptEls],
  );

  // Keyboard shortcuts: j/k
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      )
        return;
      if (e.key === "j") jumpToPrompt(1);
      if (e.key === "k") jumpToPrompt(-1);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [jumpToPrompt]);

  // Track scroll position → update prompt indicator (debounced)
  useEffect(() => {
    const panel = scrollRef.current;
    if (!panel || userPromptIndices.length === 0) return;
    let raf = 0;
    const handler = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const userEls = getUserPromptEls();
        const scrollTop = panel.scrollTop;
        let current = 0;
        for (let i = 0; i < userEls.length; i++) {
          // getBoundingClientRect is reliable regardless of nesting
          const rect = userEls[i].getBoundingClientRect();
          const panelRect = panel.getBoundingClientRect();
          if (rect.top - panelRect.top <= 60) current = i;
        }
        promptIndexRef.current = current;
        setCurrentPrompt(current + 1);
      });
    };
    panel.addEventListener("scroll", handler, { passive: true });
    return () => {
      panel.removeEventListener("scroll", handler);
      cancelAnimationFrame(raf);
    };
  }, [userPromptIndices, getUserPromptEls]);

  // Turn highlight from ?turn= query param (used by recommendation evidence links)
  const turnParam = searchParams.get("turn");
  const highlightTurn = turnParam ? parseInt(turnParam, 10) : null;
  const [turnScrolled, setTurnScrolled] = useState(false);

  // Reset scroll when session changes
  useEffect(() => {
    scrollRef.current?.scrollTo(0, 0);
    promptIndexRef.current = 0;
    setCurrentPrompt(1);

    setTurnScrolled(false);
  }, [sessionId]);

  // Scroll to highlighted turn once messages are loaded
  useEffect(() => {
    if (!highlightTurn || turnScrolled || !messages?.length) return;
    const panel = scrollRef.current;
    if (!panel) return;

    // Small delay to let DOM render
    const timer = setTimeout(() => {
      const el = panel.querySelector<HTMLElement>(`[data-turn="${highlightTurn}"]`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        setTurnScrolled(true);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [highlightTurn, turnScrolled, messages]);

  // Infinite scroll: load more messages when scrolled near bottom
  const loadMoreRef = useRef(loadMoreMessages);
  loadMoreRef.current = loadMoreMessages;
  const hasMoreRef = useRef(messagesHasMore);
  hasMoreRef.current = messagesHasMore;
  const loadingMoreRef = useRef(messagesLoadingMore);
  loadingMoreRef.current = messagesLoadingMore;

  useEffect(() => {
    const panel = scrollRef.current;
    if (!panel) return;
    let ticking = false;
    const handler = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        ticking = false;
        if (!hasMoreRef.current || loadingMoreRef.current) return;
        const { scrollTop, scrollHeight, clientHeight } = panel;
        if (scrollHeight - scrollTop - clientHeight < 500) {
          loadMoreRef.current();
        }
      });
    };
    panel.addEventListener("scroll", handler, { passive: true });
    return () => panel.removeEventListener("scroll", handler);
  }, [sessionId]);

  // Parallel session view handlers
  const handleParallelClick = useCallback(async (info: GanttClickInfo) => {
    setParallelData({
      sessions: info.activeSessions,
      clickTime: info.clickTime,
      clickDate: info.clickDate,
    });
    setParallelLoading(true);
    setParallelMessages({});

    try {
      const results = await Promise.all(
        info.activeSessions.map(async (s) => {
          const msgs = await api.messages(s.id, { limit: 2000 });
          return [s.id, msgs] as const;
        }),
      );
      const map: Record<string, Message[]> = {};
      for (const [id, msgs] of results) map[id] = msgs;
      setParallelMessages(map);
    } catch (err) {
      console.error("[parallel] fetch failed:", err);
    } finally {
      setParallelLoading(false);
    }
  }, [api]);

  const closeParallelView = useCallback(() => {
    setParallelData(null);
    setParallelMessages({});
  }, []);

  const openSessionFromParallel = useCallback((id: string) => {
    setParallelData(null);
    setParallelMessages({});
    handleSelectSession(id);
  }, [handleSelectSession]);

  // Build rendered items
  const renderedItems = useMemo(() => {
    const items: React.ReactNode[] = [];
    let seqIdx = 0;

    for (const m of visibleMessages) {
      if (isInterruption(m)) {
        items.push(
          <InterruptionBreak
            key={`int-${m.id}`}
            time={m.timestamp?.slice(11, 19) ?? ""}
          />,
        );
      }

      if (isCompaction(m)) {
        const time = m.timestamp?.slice(11, 19) ?? "";
        const isFirst = items.length === 0;
        items.push(
          <CompactionBreak
            key={`comp-${m.id}`}
            time={time}
            label={isFirst ? "Resumed from previous session" : "Context compacted"}
          />,
        );
        if (m.content) {
          items.push(
            <div key={`comp-content-${m.id}`} className="px-3">
              <details className="mt-1">
                <summary className="cursor-pointer inline-flex items-center gap-1 px-2 py-0.5 rounded text-[0.6875rem] font-semibold uppercase tracking-wide bg-amber-100 text-amber-700 hover:bg-amber-200 transition-colors">
                  <span className="text-[0.6875rem]">▶</span> compaction summary
                </summary>
                <div className="mt-1 px-3 py-2 rounded-lg text-[11px] font-mono whitespace-pre-wrap break-words max-h-96 overflow-y-auto leading-relaxed bg-amber-50/50 border border-amber-200">
                  {m.content}
                </div>
              </details>
            </div>,
          );
        }
        seqIdx++;
        continue;
      }

      items.push(
        <RichMessage
          key={m.id}
          message={m}
          seqIndex={seqIdx}
          highlighted={highlightTurn != null && m.raw_line_number === highlightTurn}
        />,
      );
      seqIdx++;
    }

    return items;
  }, [visibleMessages, highlightTurn]);

  // Compute active dates from sidebar sessions for calendar heatmap
  const activeDates = useMemo(() => {
    const map = new Map<string, number>();
    for (const s of sidebarSessions) {
      const date = s.first_seen.slice(0, 10);
      map.set(date, (map.get(date) ?? 0) + 1);
    }
    return map;
  }, [sidebarSessions]);

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Filter toolbar — full width above sidebar+messages */}
      <SessionFilterToolbar
        developers={[]}
        filters={filters}
        onFiltersChange={setFilters}
        activeDates={activeDates}
        sessionCount={sidebarSessions.length}
        hideUserFilter={true}
      />

      <div className="flex flex-1 min-h-0">
        {/* Session sidebar */}
        <SessionSidebar
          sessions={sidebarSessions}
          activeSessionId={sessionId}
          onSelectSession={handleSelectSession}
          onParallelClick={handleParallelClick}
          loading={sessionsLoading}
          hasMore={sidebarHasMore}
          onLoadMore={loadMoreSessions}
        />

        {/* Right panel: parallel view or single session */}
        {parallelData ? (
          <ParallelSessionView
            data={parallelData}
            messagesMap={parallelMessages}
            loading={parallelLoading}
            onClose={closeParallelView}
            onOpenSession={openSessionFromParallel}
          />
        ) : (
        <div className="flex-1 flex flex-col min-w-0 bg-muted">
        {messagesLoading && messages.length === 0 && (
          <div className="flex-1 p-4 space-y-4">
            <Skeleton className="h-8 w-3/4 bg-muted-foreground/15" />
            <Skeleton className="h-4 w-1/2 bg-muted-foreground/15" />
            <div className="space-y-2 pt-4">
              <Skeleton className="h-16 w-full bg-muted-foreground/15" />
              <Skeleton className="h-16 w-full bg-muted-foreground/15" />
              <Skeleton className="h-16 w-full bg-muted-foreground/15" />
              <Skeleton className="h-16 w-full bg-muted-foreground/15" />
              <Skeleton className="h-16 w-full bg-muted-foreground/15" />
            </div>
          </div>
        )}

        {session && messages.length > 0 && (
          <>
            {/* Fixed header bar */}
            <div className="flex-shrink-0">
              <SessionHeaderBar
                session={session}
                messages={messages}
              />
            </div>

            {/* Jump bar — fixed below header */}
            <div className="flex-shrink-0">
              <JumpBar
                currentPrompt={currentPrompt}
                totalPrompts={userPromptIndices.length}
                onJump={jumpToPrompt}
              />
            </div>

            {/* Messages + Minimap — only this scrolls */}
            <div className="flex flex-1 min-h-0">
              <div
                ref={scrollRef}
                className="flex-1 overflow-y-auto"
              >
                <div className="flex flex-col gap-1 p-2">
                  {renderedItems}
                  {messagesLoadingMore && (
                    <div className="py-4 space-y-2">
                      <Skeleton className="h-12 w-full" />
                      <Skeleton className="h-12 w-full" />
                    </div>
                  )}
                  {!messagesHasMore && visibleMessages.length > 0 && (
                    <div className="text-center py-3 text-[0.6875rem] text-muted-foreground">
                      End of session · {visibleMessages.length} messages
                    </div>
                  )}
                </div>
              </div>

              <Minimap
                messages={visibleMessages}
                scrollContainerRef={scrollRef}
              />
            </div>
          </>
        )}
        </div>
        )}
      </div>
    </div>
  );
}
