"use client";

import { useState } from "react";
import { parseTaggedSections } from "@/lib/session-utils";

function CollapsibleSection({
  label,
  body,
  isCodex,
}: {
  label: string;
  isCodex: boolean;
  body: string;
}) {
  const [open, setOpen] = useState(false);
  const btnCls = isCodex
    ? "bg-emerald-100 text-emerald-700 hover:bg-emerald-200"
    : "bg-muted text-muted-foreground hover:bg-muted";

  return (
    <div className="mt-1.5">
      <button
        onClick={() => setOpen(!open)}
        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[0.6875rem] font-semibold uppercase tracking-wide ${btnCls} transition-colors`}
      >
        <span
          className="text-[0.6875rem] inline-block transition-transform"
          style={{ transform: open ? "rotate(90deg)" : undefined }}
        >
          ▶
        </span>
        {label}
        {isCodex && (
          <span className="text-[0.6875rem] opacity-60 font-normal normal-case ml-1">
            codex
          </span>
        )}
      </button>
      {open && (
        <div className="mt-1 px-3 py-2 rounded-lg text-[11px] font-mono whitespace-pre-wrap break-words max-h-96 overflow-y-auto leading-relaxed bg-muted border border-border">
          {body}
        </div>
      )}
    </div>
  );
}

interface RichContentProps {
  content: string | null;
}

export function RichContent({ content }: RichContentProps) {
  if (!content) return null;
  const { plain, sections } = parseTaggedSections(content);

  return (
    <>
      {plain && (
        <div className="text-sm text-muted-foreground leading-relaxed whitespace-pre-wrap break-words mt-1.5">
          {plain}
        </div>
      )}
      {sections.map((s, i) => (
        <CollapsibleSection key={i} label={s.tag} body={s.body} isCodex={s.isCodex} />
      ))}
    </>
  );
}
