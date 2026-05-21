"use client";

import { CheckIcon, ChevronDownIcon, Loader2Icon, XCircleIcon } from "lucide-react";
import { useState } from "react";

const formatToolArgs = (argsText: string) => {
  try {
    return JSON.stringify(JSON.parse(argsText), null, 2);
  } catch {
    return argsText;
  }
};

const formatResult = (result: unknown) => {
  if (typeof result === "string") {
    try {
      return JSON.stringify(JSON.parse(result), null, 2);
    } catch {
      return result;
    }
  }
  return JSON.stringify(result, null, 2);
};

const getToolStatus = (result: unknown) => {
  if (result === undefined) {
    return { icon: Loader2Icon, color: "text-blue-500", label: "Running" };
  }
  if (typeof result === "string") {
    const trimmed = result.trim().toLowerCase();
    if (
      trimmed.startsWith("error:") ||
      trimmed.startsWith("failed:") ||
      trimmed.startsWith("exception:")
    ) {
      return { icon: XCircleIcon, color: "text-red-500", label: "Error" };
    }
  } else if (typeof result === "object" && result !== null) {
    if ("error" in result || "Error" in result) {
      return { icon: XCircleIcon, color: "text-red-500", label: "Error" };
    }
  }
  return { icon: CheckIcon, color: "text-green-500", label: "Complete" };
};

interface ToolFallbackProps {
  toolName: string;
  argsText: string;
  result?: unknown;
}

export function ToolFallback({ toolName, argsText, result }: ToolFallbackProps) {
  const [isCollapsed, setIsCollapsed] = useState(true);
  const status = getToolStatus(result);
  const StatusIcon = status.icon;

  return (
    <div className="mb-1 flex w-full flex-col rounded-lg border border-border/60 bg-gradient-to-br from-muted/80 to-muted/40 overflow-hidden">
      <button
        onClick={() => setIsCollapsed(!isCollapsed)}
        className="flex items-center gap-2 px-3 py-2 w-full text-left hover:bg-card/50 transition-colors"
      >
        <div
          className={`flex items-center justify-center w-6 h-6 rounded-md ${
            status.icon === CheckIcon
              ? "bg-green-100 dark:bg-green-900/30"
              : status.icon === XCircleIcon
                ? "bg-red-100 dark:bg-red-900/30"
                : "bg-blue-100 dark:bg-blue-900/30"
          }`}
        >
          <StatusIcon
            className={`size-3.5 ${status.color} ${status.icon === Loader2Icon ? "animate-spin" : ""}`}
          />
        </div>
        <div className="flex-grow min-w-0">
          <span className="font-mono text-xs font-medium text-foreground truncate">
            {toolName}
          </span>
        </div>
        <ChevronDownIcon
          className={`size-3.5 text-muted-foreground transition-transform ${!isCollapsed ? "rotate-180" : ""}`}
        />
      </button>

      {!isCollapsed && (
        <div className="flex flex-col gap-3 border-t border-border/60/60 bg-card/50/30 p-4">
          <div>
            <p className="text-xs font-semibold text-muted-foreground mb-2">
              Arguments
            </p>
            <pre className="whitespace-pre-wrap text-xs bg-card p-3 rounded-lg border border-border overflow-x-auto font-mono">
              {formatToolArgs(argsText)}
            </pre>
          </div>
          {result !== undefined && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-2">
                Result
              </p>
              <pre className="whitespace-pre-wrap text-xs bg-card p-3 rounded-lg border border-border overflow-x-auto max-h-96 overflow-y-auto font-mono">
                {formatResult(result)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
