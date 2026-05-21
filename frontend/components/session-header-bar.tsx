"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { Session, Message } from "@/lib/types";
import { isCompaction, isInterruption } from "@/lib/session-utils";
import { SOURCE_COLORS, type KnownSource, SOURCE_COLOR_DEFAULT } from "@/lib/constants";


interface SessionHeaderBarProps {
  session: Session;
  messages: Message[];
}

export function SessionHeaderBar({ session, messages }: SessionHeaderBarProps) {
  const [copied, setCopied] = useState(false);

  const userCount = messages.filter((m) => m.msg_type === "user").length;
  const toolCount = messages.filter((m) => m.msg_type === "tool_call").length;
  const compactCount = messages.filter(isCompaction).length;
  const interruptCount = messages.filter(isInterruption).length;

  const first = messages[0]?.timestamp?.slice(0, 16).replace("T", " ") ?? "";
  const last =
    messages[messages.length - 1]?.timestamp?.slice(0, 16).replace("T", " ") ?? "";

  const srcColor =
    SOURCE_COLORS[session.source as KnownSource] ?? SOURCE_COLOR_DEFAULT;

  const shortId = session.id.slice(0, 8);

  const copyId = async () => {
    await navigator.clipboard.writeText(session.id);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="flex items-center gap-2 px-4 py-2 bg-card border-b border-border">
      <span
        className={cn("text-[0.6875rem] font-medium px-1.5 py-0.5 rounded border shrink-0", srcColor)}
      >
        {session.source}
      </span>
      <span className="text-xs text-foreground font-semibold shrink-0">
        {messages.length} msgs
      </span>
      <span className="text-[0.6875rem] text-muted-foreground shrink-0">
        {userCount} prompts · {toolCount} tools
      </span>

      {compactCount > 0 && (
        <span className="compaction-badge shrink-0">
          ⚡ {compactCount} compact{compactCount > 1 ? "s" : ""}
        </span>
      )}
      {interruptCount > 0 && (
        <span className="interruption-badge shrink-0">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-red-500" />{" "}
          {interruptCount} interrupt{interruptCount > 1 ? "s" : ""}
        </span>
      )}

      <span className="text-[0.6875rem] text-muted-foreground/50 font-mono ml-auto shrink-0">
        {first} → {last}
      </span>

      <button
        onClick={copyId}
        className="text-[0.6875rem] text-muted-foreground hover:text-foreground font-mono px-1.5 py-0.5 rounded hover:bg-muted transition-colors cursor-pointer shrink-0"
        title={session.id}
      >
        {copied ? "copied!" : shortId}
      </button>


    </div>
  );
}
