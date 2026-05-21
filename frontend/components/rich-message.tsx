"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { MSG_STYLES, MSG_STYLE_DEFAULT } from "@/lib/constants";
import { RichContent } from "./rich-content";
import type { Message } from "@/lib/types";

function CollapsibleBlock({
  label,
  body,
  btnClass,
  bodyClass,
}: {
  label: string;
  body: string;
  btnClass: string;
  bodyClass: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-1.5">
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "inline-flex items-center gap-1 px-2 py-0.5 rounded text-[0.6875rem] font-semibold uppercase tracking-wide transition-colors",
          btnClass,
        )}
      >
        <span
          className="text-[0.6875rem] inline-block transition-transform"
          style={{ transform: open ? "rotate(90deg)" : undefined }}
        >
          ▶
        </span>
        {label}
      </button>
      {open && (
        <div
          className={cn(
            "mt-1 px-3 py-2 rounded-lg text-[11px] font-mono whitespace-pre-wrap break-words max-h-96 overflow-y-auto leading-relaxed",
            bodyClass,
          )}
        >
          {body}
        </div>
      )}
    </div>
  );
}

interface RichMessageProps {
  message: Message;
  seqIndex: number;
  highlighted?: boolean;
}

export function RichMessage({ message: m, seqIndex, highlighted }: RichMessageProps) {
  const st = MSG_STYLES[m.msg_type] ?? MSG_STYLE_DEFAULT;
  const time = m.timestamp ? m.timestamp.slice(11, 19) : "";
  const toolInput =
    m.tool_input != null
      ? typeof m.tool_input === "string"
        ? m.tool_input
        : JSON.stringify(m.tool_input, null, 2)
      : null;

  return (
    <div
      className={cn(
        st.bg, "border-l-[3px]", st.border, "rounded-r-lg px-3 py-2",
        highlighted && "ring-2 ring-amber-400 dark:ring-amber-500 ring-offset-1 bg-amber-50/50 dark:bg-amber-900/20",
      )}
      data-msgtype={m.msg_type}
      data-msg-seq={seqIndex}
      data-turn={m.raw_line_number ?? undefined}
    >
      {/* Header row */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[0.6875rem] text-muted-foreground/50 font-mono tabular-nums min-w-[2ch] text-right">
          {seqIndex}
        </span>
        <span className="text-[11px] text-muted-foreground font-mono">{time}</span>
        <span className={cn("text-[0.6875rem] font-semibold uppercase tracking-wide", st.label)}>
          {m.msg_type.replace("_", " ")}
        </span>
        {m.tool_name && (
          <span className="text-[11px] font-semibold text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded">
            {m.tool_name}
          </span>
        )}
        {m.tool_output != null && (
          <span
            className={cn(
              "text-[0.6875rem] font-semibold",
              m.tool_status === "success" ? "text-emerald-600" : "text-red-500",
            )}
          >
            {m.tool_status === "success"
              ? m.tool_output.trim()
                ? "OK"
                : "no output"
              : "FAIL"}
          </span>
        )}
      </div>

      {/* Content */}
      <RichContent content={m.content} />

      {/* Thinking */}
      {m.thinking && (
        <CollapsibleBlock
          label="thinking"
          body={m.thinking}
          btnClass="bg-violet-100 text-violet-600 hover:bg-violet-200"
          bodyClass="bg-violet-50/50 border border-violet-100"
        />
      )}

      {/* Tool input */}
      {toolInput && (
        <CollapsibleBlock
          label="input"
          body={toolInput}
          btnClass="bg-amber-100/80 text-amber-700 hover:bg-amber-200"
          bodyClass="bg-amber-50/50 border border-amber-100"
        />
      )}

      {/* Tool output */}
      {m.tool_output && (
        <CollapsibleBlock
          label="output"
          body={m.tool_output}
          btnClass={
            m.tool_status === "success"
              ? "bg-slate-100 text-slate-500 hover:bg-slate-200"
              : "bg-red-100 text-red-600 hover:bg-red-200"
          }
          bodyClass={
            m.tool_status === "success"
              ? "bg-slate-50 border border-slate-100"
              : "bg-red-50 border border-red-100"
          }
        />
      )}
    </div>
  );
}
