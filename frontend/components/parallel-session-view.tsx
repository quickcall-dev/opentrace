"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { SourceBadge } from "./source-badge";
import { RichContent } from "./rich-content";
import { MSG_STYLES, MSG_STYLE_DEFAULT } from "@/lib/constants";
import { filterVisibleMessages } from "@/lib/session-utils";
import type { Session, Message } from "@/lib/types";

/* ── Split pane message rendering ── */

function SplitMessage({ message: m, isHighlighted }: { message: Message; isHighlighted?: boolean }) {
  const st = MSG_STYLES[m.msg_type] ?? MSG_STYLE_DEFAULT;
  const time = m.timestamp ? m.timestamp.slice(11, 19) : "";
  const [inputOpen, setInputOpen] = useState(false);
  const [outputOpen, setOutputOpen] = useState(false);

  const toolInput =
    m.tool_input != null
      ? typeof m.tool_input === "string"
        ? m.tool_input
        : JSON.stringify(m.tool_input, null, 2)
      : null;

  return (
    <div
      className={cn(
        st.bg,
        "border-l-[3px]",
        st.border,
        "rounded-r-lg px-2 py-1.5 mb-1 text-[12px]",
        isHighlighted && "ring-2 ring-blue-400/40",
      )}
      data-msgtype={m.msg_type}
    >
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-[0.6875rem] text-muted-foreground font-mono">{time}</span>
        <span className={cn("text-[0.6875rem] font-semibold uppercase tracking-wide", st.label)}>
          {m.msg_type.replace("_", " ")}
        </span>
        {m.tool_name && (
          <span className="text-[0.6875rem] font-semibold text-amber-700">{m.tool_name}</span>
        )}
        {m.tool_output != null && (
          <span
            className={cn(
              "text-[0.6875rem] font-semibold",
              m.tool_status === "success" ? "text-emerald-600" : "text-red-500",
            )}
          >
            {m.tool_status === "success"
              ? m.tool_output.trim() ? "OK" : "no output"
              : "FAIL"}
          </span>
        )}
      </div>

      <RichContent content={m.content} />

      {toolInput && (
        <div className="mt-1">
          <button
            onClick={() => setInputOpen(!inputOpen)}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[0.6875rem] font-semibold uppercase tracking-wide bg-amber-100/80 text-amber-700 hover:bg-amber-200 transition-colors"
          >
            <span className="text-[0.6875rem]" style={{ transform: inputOpen ? "rotate(90deg)" : undefined, display: "inline-block", transition: "transform 0.15s" }}>▶</span>
            input
          </button>
          {inputOpen && (
            <div className="mt-1 px-3 py-2 rounded-lg text-[11px] font-mono whitespace-pre-wrap break-words max-h-96 overflow-y-auto leading-relaxed bg-amber-50/50 border border-amber-100">
              {toolInput}
            </div>
          )}
        </div>
      )}

      {m.tool_output && (
        <div className="mt-1">
          <button
            onClick={() => setOutputOpen(!outputOpen)}
            className={cn(
              "inline-flex items-center gap-1 px-2 py-0.5 rounded text-[0.6875rem] font-semibold uppercase tracking-wide transition-colors",
              m.tool_status === "success"
                ? "bg-slate-100 text-slate-500 hover:bg-slate-200"
                : "bg-red-100 text-red-600 hover:bg-red-200",
            )}
          >
            <span className="text-[0.6875rem]" style={{ transform: outputOpen ? "rotate(90deg)" : undefined, display: "inline-block", transition: "transform 0.15s" }}>▶</span>
            output
          </button>
          {outputOpen && (
            <div className={cn(
              "mt-1 px-3 py-2 rounded-lg text-[11px] font-mono whitespace-pre-wrap break-words max-h-96 overflow-y-auto leading-relaxed",
              m.tool_status === "success"
                ? "bg-slate-50 border border-slate-100"
                : "bg-red-50 border border-red-100",
            )}>
              {m.tool_output}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Single split pane ── */

function SplitPane({
  session,
  messages,
  clickTime,
  totalPanes,
  onOpenFull,
}: {
  session: Session;
  messages: Message[];
  clickTime: string;
  totalPanes: number;
  onOpenFull: (id: string) => void;
}) {
  const paneRef = useRef<HTMLDivElement>(null);
  const anchorRef = useRef<HTMLDivElement>(null);
  const [promptPos, setPromptPos] = useState("prompt 1/1");

  const visible = useMemo(() => filterVisibleMessages(messages), [messages]);

  const userIndices = useMemo(
    () => visible.reduce<number[]>((acc, m, i) => { if (m.msg_type === "user") acc.push(i); return acc; }, []),
    [visible],
  );

  // Find closest user prompt to click time
  const closestIdx = useMemo(() => {
    if (!clickTime || userIndices.length === 0) return 0;
    const date = session.first_seen.slice(0, 10);
    const clickTs = new Date(`${date}T${clickTime}:00Z`).getTime();
    let best = 0;
    let bestDist = Infinity;
    for (let i = 0; i < userIndices.length; i++) {
      const m = visible[userIndices[i]];
      const mTs = new Date(m.timestamp).getTime();
      const dist = Math.abs(mTs - clickTs);
      if (dist < bestDist) { bestDist = dist; best = i; }
    }
    return best;
  }, [clickTime, userIndices, visible, session.first_seen]);

  // Scroll to anchor on mount
  useEffect(() => {
    requestAnimationFrame(() => {
      anchorRef.current?.scrollIntoView({ block: "start" });
    });
  }, [closestIdx]);

  useEffect(() => {
    setPromptPos(`prompt ${closestIdx + 1}/${userIndices.length}`);
  }, [closestIdx, userIndices.length]);

  const jump = useCallback((dir: number) => {
    const pane = paneRef.current;
    if (!pane || userIndices.length === 0) return;
    const userEls = [...pane.querySelectorAll<HTMLElement>('[data-msgtype="user"]')];
    if (!userEls.length) return;
    const headerH = 60;
    let current = 0;
    for (let i = 0; i < userEls.length; i++) {
      if (userEls[i].offsetTop <= pane.scrollTop + headerH + 20) current = i;
    }
    const next = Math.max(0, Math.min(userEls.length - 1, current + dir));
    userEls[next].scrollIntoView({ behavior: "smooth", block: "start" });
    setPromptPos(`prompt ${next + 1}/${userEls.length}`);
  }, [userIndices.length]);

  const repoShort = session.repo_name ? String(session.repo_name).split("/").pop() : "";

  return (
    <div ref={paneRef} className={cn(
      "shrink-0 overflow-y-auto border-r border-border last:border-r-0",
      totalPanes === 1 && "w-full",
      totalPanes === 2 && "w-1/2",
      totalPanes >= 3 && "w-1/3 min-w-[33.333%]",
    )}>
      {/* Sticky pane header */}
      <div className="sticky top-0 z-10 bg-card border-b border-border px-3 py-2">
        <div
          className="flex items-center gap-2 cursor-pointer hover:bg-blue-50 rounded px-1 -mx-1 transition-colors"
          onClick={() => onOpenFull(session.id)}
          title="Click to open full session"
        >
          <SourceBadge source={session.source} />
          <span className="text-[0.6875rem] text-muted-foreground">{messages.length} msgs</span>
          {repoShort && <span className="text-[0.6875rem] text-muted-foreground">{repoShort}</span>}
          <span className="text-[0.6875rem] text-muted-foreground ml-auto underline">open full →</span>
        </div>
        <div className="flex items-center gap-1.5 mt-1 h-5">
          <span className="text-[0.6875rem] text-muted-foreground/50 font-mono truncate">{session.id}</span>
          <span className="text-muted-foreground/30 mx-0.5">|</span>
          <span className="text-[0.6875rem] text-muted-foreground font-mono shrink-0">{promptPos}</span>
          <button
            onClick={() => jump(-1)}
            disabled={userIndices.length < 2}
            className="text-[0.6875rem] px-1 py-0.5 rounded hover:bg-muted text-muted-foreground font-semibold disabled:opacity-30 disabled:cursor-default shrink-0"
            title="Previous prompt"
          >
            ▲
          </button>
          <button
            onClick={() => jump(1)}
            disabled={userIndices.length < 2}
            className="text-[0.6875rem] px-1 py-0.5 rounded hover:bg-muted text-muted-foreground font-semibold disabled:opacity-30 disabled:cursor-default shrink-0"
            title="Next prompt"
          >
            ▼
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="p-2 flex flex-col gap-0.5">
        {visible.map((m, i) => {
          const isAnchor = userIndices[closestIdx] === i;
          return (
            <div key={m.id} ref={isAnchor ? anchorRef : undefined}>
              <SplitMessage message={m} isHighlighted={isAnchor} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Main parallel view ── */

export interface ParallelViewData {
  sessions: Session[];
  clickTime: string;
  clickDate: string;
}

interface ParallelSessionViewProps {
  data: ParallelViewData;
  messagesMap: Record<string, Message[]>;
  loading?: boolean;
  onClose: () => void;
  onOpenSession: (id: string) => void;
}

export function ParallelSessionView({
  data,
  messagesMap,
  loading,
  onClose,
  onOpenSession,
}: ParallelSessionViewProps) {
  const formatDate = (d: string) => {
    const dt = new Date(d + "T00:00:00");
    return dt.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center flex-1 text-muted-foreground text-sm gap-2">
        <span className="inline-block w-3.5 h-3.5 border-2 border-border border-t-foreground rounded-full animate-spin" />
        Loading parallel sessions...
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-muted">
      {/* Header */}
      <div className="flex-shrink-0 bg-card border-b border-border px-4 py-2 flex items-center gap-3">
        <span className="text-xs font-semibold text-red-500 font-mono">{data.clickTime}</span>
        <span className="text-xs text-muted-foreground">{formatDate(data.clickDate)}</span>
        <span className="text-xs text-muted-foreground">{data.sessions.length} parallel sessions</span>
        <button
          onClick={onClose}
          className="ml-auto text-[0.6875rem] text-muted-foreground hover:text-muted-foreground px-2 py-0.5 rounded hover:bg-muted"
        >
          close ✕
        </button>
      </div>

      {/* Split panes — show 3 at a time, scroll horizontally for more */}
      <div className="flex flex-1 min-h-0 overflow-x-auto">
        {data.sessions.map((s) => (
          <SplitPane
            key={s.id}
            session={s}
            messages={messagesMap[s.id] ?? []}
            clickTime={data.clickTime}
            totalPanes={data.sessions.length}
            onOpenFull={onOpenSession}
          />
        ))}
      </div>
    </div>
  );
}
