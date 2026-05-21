"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { SourceBadge } from "@/components/source-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { CalendarPicker } from "@/components/calendar-picker";
import {
  Dropdown,
  DropdownTrigger,
  DropdownContent,
} from "@/components/ui/dropdown";
import type { Session, Developer } from "@/lib/types";

/* ── Helpers ── */

function formatDate(d: string) {
  const dt = new Date(d + "T00:00:00");
  return dt.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

function timeToMinutes(ts: string) {
  const h = parseInt(ts.slice(11, 13));
  const m = parseInt(ts.slice(14, 16));
  return h * 60 + m;
}

function durationLabel(mins: number) {
  if (mins < 1) return "<1m";
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const rm = mins % 60;
  return rm ? `${h}h${rm}m` : `${h}h`;
}

function assignLanes(sessions: Session[]) {
  const sorted = [...sessions].sort((a, b) =>
    a.first_seen.localeCompare(b.first_seen),
  );
  const lanes: Date[] = [];
  const assignments = new Map<string, number>();
  for (const s of sorted) {
    const sStart = new Date(s.first_seen);
    let placed = false;
    for (let i = 0; i < lanes.length; i++) {
      if (sStart >= lanes[i]) {
        lanes[i] = new Date(s.last_updated);
        assignments.set(s.id, i);
        placed = true;
        break;
      }
    }
    if (!placed) {
      assignments.set(s.id, lanes.length);
      lanes.push(new Date(s.last_updated));
    }
  }
  return { assignments, laneCount: lanes.length };
}

function detectOverlaps(sessions: Session[]): boolean {
  for (let i = 0; i < sessions.length; i++) {
    for (let j = i + 1; j < sessions.length; j++) {
      const aStart = new Date(sessions[i].first_seen).getTime();
      const aEnd = new Date(sessions[i].last_updated).getTime();
      const bStart = new Date(sessions[j].first_seen).getTime();
      const bEnd = new Date(sessions[j].last_updated).getTime();
      if (aStart < bEnd && bStart < aEnd) return true;
    }
  }
  return false;
}

/* ── Colors ── */

const GANTT_COLORS: Record<string, string> = {
  claude_code: "bg-[#E8926C] text-white",
  codex_cli: "bg-[#10A37F] text-white",
  gemini_cli: "bg-[#4285F4] text-white",
  cursor: "bg-[#7B61FF] text-white",
  cursor_vscdb: "bg-[#A855F7] text-white",
  pi: "bg-[#FF6B35] text-white",
};
const GANTT_DEFAULT = "bg-muted-foreground text-background";

const DOT_COLORS: Record<string, string> = {
  claude_code: "bg-[#E8926C]",
  codex_cli: "bg-[#10A37F]",
  gemini_cli: "bg-[#4285F4]",
  cursor: "bg-[#7B61FF]",
  cursor_vscdb: "bg-[#A855F7]",
  pi: "bg-[#FF6B35]",
};

const SOURCE_LABELS: Record<string, string> = {
  claude_code: "Claude Code",
  codex_cli: "Codex CLI",
  gemini_cli: "Gemini CLI",
  cursor: "Cursor",
  cursor_vscdb: "Cursor DB",
  pi: "Pi",
};

const ALL_SOURCES = ["claude_code", "codex_cli", "gemini_cli", "cursor", "cursor_vscdb", "pi"];

/* ── Gantt Chart ── */

export interface GanttClickInfo {
  activeSessions: Session[];
  clickTime: string;
  clickDate: string;
}

function GanttChart({
  sessions,
  activeId,
  onSelect,
  onParallelClick,
}: {
  sessions: Session[];
  activeId: string;
  onSelect: (id: string) => void;
  onParallelClick?: (info: GanttClickInfo) => void;
}) {
  const { assignments, laneCount } = useMemo(
    () => assignLanes(sessions),
    [sessions],
  );

  const date = sessions[0].first_seen.slice(0, 10);
  let minH = 24;
  let maxH = 0;
  for (const s of sessions) {
    const sh = parseInt(s.first_seen.slice(11, 13));
    const endDate = s.last_updated.slice(0, 10);
    const eh = endDate !== date ? 24 : parseInt(s.last_updated.slice(11, 13)) + 1;
    minH = Math.min(minH, sh);
    maxH = Math.max(maxH, eh);
  }
  minH = Math.max(0, minH);
  maxH = Math.min(24, maxH);
  const hourSpan = maxH - minH || 1;

  const areaRef = useRef<HTMLDivElement>(null);
  const cursorRef = useRef<HTMLDivElement>(null);
  const labelRef = useRef<HTMLDivElement>(null);

  const pctToTime = (pct: number) => {
    const totalMin = minH * 60 + pct * hourSpan * 60;
    const h = Math.floor(totalMin / 60);
    const m = Math.floor(totalMin % 60);
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
  };

  const handleAreaMouseMove = (e: React.MouseEvent) => {
    if (!areaRef.current || !cursorRef.current || !labelRef.current) return;
    const rect = areaRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const pct = x / rect.width;
    cursorRef.current.style.left = `${x}px`;
    cursorRef.current.style.display = "block";
    labelRef.current.textContent = pctToTime(pct);
  };

  const handleAreaMouseLeave = () => {
    if (cursorRef.current) cursorRef.current.style.display = "none";
  };

  const handleAreaClick = (e: React.MouseEvent) => {
    if (!areaRef.current) return;

    const rect = areaRef.current.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    const clickMin = minH * 60 + pct * hourSpan * 60;
    const clickTime = pctToTime(pct);

    const activeSessions = sessions.filter((s) => {
      const sMin = timeToMinutes(s.first_seen);
      const eWraps = s.last_updated.slice(0, 10) !== date;
      const eMin = eWraps ? 24 * 60 : timeToMinutes(s.last_updated);
      return clickMin >= sMin && clickMin <= eMin;
    });

    if (activeSessions.length <= 1) {
      // Single or no session — let bar onClick handle it, or find closest
      if (activeSessions.length === 0) {
        let closest: Session | null = null;
        let closestDist = Infinity;
        for (const s of sessions) {
          const sMin = timeToMinutes(s.first_seen);
          const eWraps = s.last_updated.slice(0, 10) !== date;
          const eMin = eWraps ? 24 * 60 : timeToMinutes(s.last_updated);
          const dist = Math.min(Math.abs(clickMin - sMin), Math.abs(clickMin - eMin));
          if (dist < closestDist) { closestDist = dist; closest = s; }
        }
        if (closest) onSelect(closest.id);
      } else {
        onSelect(activeSessions[0].id);
      }
      return;
    }

    // Multiple sessions overlap — trigger parallel view
    if (onParallelClick) {
      e.stopPropagation();
      onParallelClick({ activeSessions, clickTime, clickDate: date });
    } else {
      onSelect(activeSessions[0].id);
    }
  };

  return (
    <div className="bg-card rounded-lg border border-border p-2 mb-2">
      <div className="flex border-b border-border/50 mb-1">
        {Array.from({ length: maxH - minH }, (_, i) => (
          <div
            key={i}
            className="flex-1 text-center text-[0.6875rem] text-muted-foreground/50 font-mono py-0.5"
          >
            {String(minH + i).padStart(2, "0")}
          </div>
        ))}
      </div>
      <div
        ref={areaRef}
        className={cn("relative", laneCount > 6 ? "max-h-[180px] overflow-y-auto" : "")}
        onMouseMove={handleAreaMouseMove}
        onMouseLeave={handleAreaMouseLeave}
        onClick={handleAreaClick}
      >
        {/* Time cursor */}
        <div
          ref={cursorRef}
          className="absolute top-0 bottom-0 w-px bg-red-400/50 pointer-events-none z-20"
          style={{ display: "none" }}
        >
          <div ref={labelRef} className="absolute -top-4 left-1/2 -translate-x-1/2 text-[0.6875rem] font-mono text-red-500 bg-card px-1 rounded shadow-sm" />
        </div>

        {Array.from({ length: laneCount }, (_, lane) => (
          <div key={lane} className="relative h-7 mb-0.5">
            {sessions
              .filter((s) => assignments.get(s.id) === lane)
              .map((s) => {
                const startMin = timeToMinutes(s.first_seen);
                const endWraps = s.last_updated.slice(0, 10) !== date;
                const endMin = endWraps ? 24 * 60 : timeToMinutes(s.last_updated);
                const left = ((startMin - minH * 60) / (hourSpan * 60)) * 100;
                const width = Math.max(1.5, ((endMin - startMin) / (hourSpan * 60)) * 100);
                const dur = Math.round(endMin - startMin);
                const repoShort = s.repo_name ? String(s.repo_name).split("/").pop() : "";
                const label =
                  width > 14
                    ? `${s.first_seen.slice(11, 16)}–${endWraps ? "00:00+" : s.last_updated.slice(11, 16)} ${durationLabel(dur)}${repoShort ? " · " + repoShort : ""}`
                    : width > 6
                      ? durationLabel(dur)
                      : "";

                return (
                  <div
                    key={s.id}
                    className={cn(
                      "absolute h-6 top-0.5 rounded cursor-pointer flex items-center px-1.5 text-[0.6875rem] font-medium whitespace-nowrap overflow-hidden transition-all opacity-85 hover:opacity-100 hover:shadow-md hover:z-10",
                      GANTT_COLORS[s.source] ?? GANTT_DEFAULT,
                      activeId === s.id && "opacity-100 ring-2 ring-blue-500/50 z-10",
                    )}
                    style={{ left: `${left}%`, width: `${width}%` }}
                    onClick={(e) => {
                      e.stopPropagation();
                      // Check if other sessions overlap at the midpoint of this bar
                      const midMin = (startMin + endMin) / 2;
                      const overlapping = sessions.filter((other) => {
                        if (other.id === s.id) return true;
                        const oStart = timeToMinutes(other.first_seen);
                        const oWraps = other.last_updated.slice(0, 10) !== date;
                        const oEnd = oWraps ? 24 * 60 : timeToMinutes(other.last_updated);
                        return midMin >= oStart && midMin <= oEnd;
                      });
                      if (overlapping.length > 1 && onParallelClick) {
                        onParallelClick({ activeSessions: overlapping, clickTime: s.first_seen.slice(11, 16), clickDate: date });
                      } else {
                        onSelect(s.id);
                      }
                    }}
                    title={`${s.first_seen.slice(11, 16)}–${s.last_updated.slice(11, 16)} ${durationLabel(dur)} ${s.source}${repoShort ? " · " + repoShort : ""}`}
                  >
                    {label}
                  </div>
                );
              })}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Timeline Node ── */

function TimelineNode({
  session,
  isActive,
  isLast,
  onSelect,
}: {
  session: Session;
  isActive: boolean;
  isLast: boolean;
  onSelect: () => void;
}) {
  const startTime = session.first_seen.slice(11, 16);
  const endTime = session.last_updated.slice(11, 16);
  const dur = Math.round(
    (new Date(session.last_updated).getTime() - new Date(session.first_seen).getTime()) / 60000,
  );
  const repoShort = session.repo_name ? String(session.repo_name).split("/").pop() : "";
  const dotColor = DOT_COLORS[session.source] ?? "bg-muted-foreground";

  return (
    <div
      className={cn(
        "flex gap-3 cursor-pointer group",
      )}
      onClick={onSelect}
    >
      {/* Left column: dot + line */}
      <div className="flex flex-col items-center flex-shrink-0 w-3">
        <div
          className={cn(
            "w-2.5 h-2.5 rounded-full flex-shrink-0 mt-2",
            dotColor,
            isActive && "ring-2 ring-blue-400/40",
          )}
        />
        {!isLast && <div className="w-px flex-1 bg-muted mt-1" />}
      </div>

      {/* Right column: content */}
      <div
        className={cn(
          "flex-1 min-w-0 py-1.5 px-2 rounded-lg mb-1 transition-colors",
          isActive ? "bg-blue-50" : "group-hover:bg-muted",
        )}
      >
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-sm font-semibold text-foreground">{startTime}</span>
          <span className="text-[0.6875rem] text-muted-foreground/50">&rarr;</span>
          <span className="text-sm text-muted-foreground">{endTime}</span>
          <span className="text-[0.6875rem] text-muted-foreground">{durationLabel(dur)}</span>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          <SourceBadge source={session.source} />
          <span className="text-[0.6875rem] text-muted-foreground">{session.message_count} msgs</span>
        </div>
        {(repoShort || session.git_branch) && (
          <div className="flex items-center gap-1.5 mt-0.5 text-[0.6875rem] text-muted-foreground truncate">
            {repoShort && <span title={session.repo_name ?? ""}>{repoShort}</span>}
            {repoShort && session.git_branch && <span className="text-muted-foreground/30">&middot;</span>}
            {session.git_branch && (
              <span className="truncate max-w-[8rem]" title={session.git_branch}>
                {session.git_branch}
              </span>
            )}
          </div>
        )}
        {session.user_email && (
          <div className="text-[0.6875rem] text-muted-foreground/50 mt-0.5 truncate">
            {session.user_name || session.user_email}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Types ── */

export type LoadMoreFn = () => Promise<void>;

export interface SidebarFilters {
  developers: string[];
  sources: string[];
  date: string | undefined;
}

/* ── Checkbox Dropdown (dumb — no local state, parent controls selection) ── */

function CheckboxDropdown({
  label,
  options,
  selected,
  onToggle,
  onSelectAll,
  onDeselectAll,
}: {
  label: string;
  options: { value: string; label: string; count?: number }[];
  selected: string[];
  onToggle: (val: string) => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
}) {
  const displayLabel = selected.length === 0
    ? label
    : selected.length === 1
      ? (options.find((o) => o.value === selected[0])?.label ?? selected[0])
      : `${selected.length} selected`;

  return (
    <Dropdown>
      <DropdownTrigger variant={selected.length > 0 ? "active" : "default"}>
        <span className="truncate max-w-[120px]">{displayLabel}</span>
      </DropdownTrigger>
      <DropdownContent className="min-w-[180px] max-h-[320px] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-3 py-1.5 border-b border-border text-[0.6875rem]">
          <button onClick={onSelectAll} className="text-foreground font-medium">All</button>
          <button onClick={onDeselectAll} className="text-muted-foreground hover:text-muted-foreground">None</button>
        </div>
        <div className="overflow-y-auto flex-1 py-1">
          {options.map((opt) => (
            <label
              key={opt.value}
              className="flex items-center gap-2 px-3 py-1.5 hover:bg-muted cursor-pointer text-xs text-foreground"
            >
              <input
                type="checkbox"
                checked={selected.includes(opt.value)}
                onChange={() => onToggle(opt.value)}
                className="rounded border-border text-foreground focus:ring-ring h-3.5 w-3.5"
              />
              <span className="truncate">{opt.label}</span>
              {opt.count !== undefined && (
                <span className="ml-auto text-[0.6875rem] text-muted-foreground tabular-nums">{opt.count}</span>
              )}
            </label>
          ))}
        </div>
      </DropdownContent>
    </Dropdown>
  );
}

/* ── Filter Toolbar — manages draft state, single Apply button ── */

export function SessionFilterToolbar({
  developers = [],
  filters,
  onFiltersChange,
  activeDates,
  sessionCount,
  hideUserFilter = false,
}: {
  developers: Developer[];
  filters: SidebarFilters;
  onFiltersChange: (filters: SidebarFilters) => void;
  activeDates?: Map<string, number>;
  sessionCount: number;
  hideUserFilter?: boolean;
}) {
  // Draft state — only pushed to parent on Apply
  const [draftDevs, setDraftDevs] = useState<string[]>(filters.developers);
  const [draftSrcs, setDraftSrcs] = useState<string[]>(filters.sources);
  const [draftDate, setDraftDate] = useState<string | undefined>(filters.date);

  // Sync draft when parent filters change (e.g. clear, URL nav)
  const committedDevsKey = filters.developers.slice().sort().join(",");
  const committedSrcsKey = filters.sources.slice().sort().join(",");
  const committedDate = filters.date ?? "";
  useEffect(() => {
    setDraftDevs(filters.developers);
    setDraftSrcs(filters.sources);
    setDraftDate(filters.date);
  }, [committedDevsKey, committedSrcsKey, committedDate]);

  const toggleDev = (email: string) => {
    setDraftDevs((prev) =>
      prev.includes(email) ? prev.filter((v) => v !== email) : [...prev, email],
    );
  };

  const toggleSource = (src: string) => {
    setDraftSrcs((prev) =>
      prev.includes(src) ? prev.filter((v) => v !== src) : [...prev, src],
    );
  };

  const apply = () => {
    onFiltersChange({ developers: draftDevs, sources: draftSrcs, date: draftDate });
  };
  const clear = () => {
    onFiltersChange({ developers: [], sources: [], date: undefined });
  };

  const draftDevsKey = draftDevs.slice().sort().join(",");
  const draftSrcsKey = draftSrcs.slice().sort().join(",");
  const dirty = draftDevsKey !== committedDevsKey
    || draftSrcsKey !== committedSrcsKey
    || (draftDate ?? "") !== committedDate;

  const uniqueDevs = useMemo(() =>
    developers.filter((d, i, arr) => arr.findIndex((x) => x.user_email === d.user_email) === i),
    [developers],
  );

  const devOptions = useMemo(() =>
    uniqueDevs.map((d) => ({
      value: d.user_email,
      label: d.user_name || d.user_email.split("@")[0],
      count: d.session_count,
    })),
    [uniqueDevs],
  );

  const sourceOptions = ALL_SOURCES.map((s) => ({
    value: s,
    label: SOURCE_LABELS[s],
  }));

  const activeFilterCount = filters.developers.length + filters.sources.length + (filters.date ? 1 : 0);

  return (
    <div className="bg-card border-b border-border flex-shrink-0">
      <div className="px-3 py-1.5 flex items-center gap-2">
        {!hideUserFilter && (
          <CheckboxDropdown
            label="All devs"
            options={devOptions}
            selected={draftDevs}
            onToggle={toggleDev}
            onSelectAll={() => setDraftDevs(devOptions.map((d) => d.value))}
            onDeselectAll={() => setDraftDevs([])}
          />
        )}

        <CheckboxDropdown
          label="All tools"
          options={sourceOptions}
          selected={draftSrcs}
          onToggle={toggleSource}
          onSelectAll={() => setDraftSrcs(ALL_SOURCES.slice())}
          onDeselectAll={() => setDraftSrcs([])}
        />

        <CalendarPicker
          value={draftDate}
          onChange={setDraftDate}
          activeDates={activeDates}
        />

        {/* Single Apply button */}
        <button
          onClick={apply}
          disabled={!dirty}
          className={cn(
            "text-xs font-medium px-3 py-1 rounded-md transition-colors",
            dirty
              ? "bg-foreground text-background hover:bg-foreground/90"
              : "bg-muted text-muted-foreground/50 cursor-default",
          )}
        >
          Apply
        </button>

        <div className="ml-auto flex items-center gap-3">
          {activeFilterCount > 0 && (
            <button
              onClick={clear}
              className="text-[0.6875rem] text-foreground underline decoration-muted-foreground/40 hover:decoration-foreground transition-colors"
            >
              Clear filters
            </button>
          )}
          <span className="text-[0.6875rem] text-muted-foreground font-mono">
            {sessionCount} sessions
          </span>
        </div>
      </div>
    </div>
  );
}

/* ── Session List (sidebar) ── */

interface SessionSidebarProps {
  sessions: Session[];
  activeSessionId: string;
  onSelectSession: (id: string) => void;
  onParallelClick?: (info: GanttClickInfo) => void;
  loading?: boolean;
  hasMore?: boolean;
  onLoadMore?: LoadMoreFn;
}

export function SessionSidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onParallelClick,
  loading,
  hasMore,
  onLoadMore,
}: SessionSidebarProps) {
  const [loadingMore, setLoadingMore] = useState(false);

  // Group by date
  const byDate = useMemo(() => {
    const map: Record<string, Session[]> = {};
    for (const s of sessions) {
      const d = s.first_seen.slice(0, 10);
      if (!map[d]) map[d] = [];
      map[d].push(s);
    }
    for (const d of Object.keys(map)) {
      map[d].sort((a, b) => a.first_seen.localeCompare(b.first_seen));
    }
    return map;
  }, [sessions]);

  const sortedDates = useMemo(() => Object.keys(byDate).sort().reverse(), [byDate]);

  return (
    <div data-testid="session-sidebar" className="w-[340px] min-w-[280px] flex-shrink-0 border-r border-border bg-card overflow-y-auto overscroll-contain py-3 px-2.5">
      {loading && sessions.length === 0 && (
        <div className="space-y-4 py-3">
          {/* Date header skeleton */}
          <div className="px-1">
            <Skeleton className="h-3.5 w-24 bg-muted-foreground/15" />
          </div>
          {/* Gantt chart skeleton */}
          <div className="px-1">
            <div className="bg-card rounded-lg border border-border p-2 mb-2 space-y-2">
              <div className="flex gap-1 border-b border-border/50 pb-1">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-3 flex-1 bg-muted-foreground/10" />
                ))}
              </div>
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-5 w-full bg-muted-foreground/10" />
              ))}
            </div>
          </div>
          {/* Timeline node skeletons */}
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex items-start gap-2.5 px-1">
                <Skeleton className="h-2.5 w-2.5 rounded-full mt-1.5 flex-shrink-0 bg-muted-foreground/15" />
                <div className="flex-1 space-y-1.5">
                  <Skeleton className="h-3.5 w-3/4 bg-muted-foreground/15" />
                  <div className="flex items-center gap-2">
                    <Skeleton className="h-3 w-16 rounded-sm bg-muted-foreground/15" />
                    <Skeleton className="h-3 w-10 rounded-sm bg-muted-foreground/15" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Date groups */}
      {sortedDates.map((date) => {
        const daySessions = byDate[date];
        const hasParallel = daySessions.length >= 2 && detectOverlaps(daySessions);
        return (
          <div key={date} className="mb-5">
            <div className="flex items-center gap-2 mb-2 px-1">
              <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                {formatDate(date)}
              </span>
              <span className="text-[0.6875rem] text-muted-foreground/50">{daySessions.length} sessions</span>
              {hasParallel && (
                <span className="text-[0.6875rem] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-100 text-amber-600">
                  PARALLEL
                </span>
              )}
            </div>

            {daySessions.length >= 2 && (
              <GanttChart sessions={daySessions} activeId={activeSessionId} onSelect={onSelectSession} onParallelClick={onParallelClick} />
            )}

            <div>
              {daySessions.map((s, i) => (
                <TimelineNode
                  key={s.id}
                  session={s}
                  isActive={activeSessionId === s.id}
                  isLast={i === daySessions.length - 1}
                  onSelect={() => onSelectSession(s.id)}
                />
              ))}
            </div>
          </div>
        );
      })}

      {hasMore && sessions.length > 0 && (
        <div className="py-3">
          <button
            onClick={async () => {
              if (!onLoadMore || loadingMore) return;
              setLoadingMore(true);
              try { await onLoadMore(); } finally { setLoadingMore(false); }
            }}
            disabled={loadingMore}
            className="w-full text-[11px] text-muted-foreground hover:text-foreground bg-muted hover:bg-muted rounded-md py-1.5 transition-colors disabled:opacity-50"
          >
            {loadingMore ? "Loading..." : "Load more sessions"}
          </button>
        </div>
      )}

      {sessions.length === 0 && !loading && (
        <div className="flex items-center justify-center py-20 text-muted-foreground/50 text-sm">
          No sessions match filters
        </div>
      )}
    </div>
  );
}
