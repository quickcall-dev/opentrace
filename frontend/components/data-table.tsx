"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useTracesApi } from "@/hooks/use-traces-api";
import { useTracesContext } from "@/context/traces-context";
import { usePolling } from "@/hooks/use-polling";
import { SourceBadge } from "@/components/source-badge";
import { EmptyState } from "@/components/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { MessageSquare } from "lucide-react";
import type { Session } from "@/lib/types";

const PAGE_SIZE = 50;

const KNOWN_SOURCES = [
  "claude_code",
  "codex_cli",
  "gemini_cli",
  "cursor",
  "cursor_vscdb",
  "pi",
];

export function DataTable({ date }: { date?: string }) {
  const router = useRouter();
  const { sessions } = useTracesApi();
  const { isReady } = useTracesContext();
  const [source, setSource] = useState("all");
  const [offset, setOffset] = useState(0);

  const fetcher = useCallback(
    () =>
      sessions({
        source: source === "all" ? undefined : source,
        limit: PAGE_SIZE,
        offset,
        date,
      }),
    [sessions, source, offset, date],
  );

  const { data, error, loading } = usePolling<Session[]>(fetcher, 30000, isReady);

  const handleSourceChange = (s: string) => {
    setSource(s);
    setOffset(0);
  };

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground">
          Sessions
        </h2>
        <div className="flex gap-1">
          {["all", ...KNOWN_SOURCES].map((s) => (
            <button
              key={s}
              onClick={() => handleSourceChange(s)}
              className={cn(
                "text-xs px-2 py-1 rounded transition-colors",
                source === s
                  ? "bg-foreground text-background"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted",
              )}
            >
              {s === "all" ? "All" : s.replaceAll("_", " ")}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="p-4 text-red-500 text-sm">Error: {error}</p>}

      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[900px]">
          <thead>
            <tr className="text-left text-xs text-muted-foreground uppercase tracking-wide border-b border-border">
              <th className="px-4 py-2">Source</th>
              <th className="px-4 py-2">Session ID</th>
              <th className="px-4 py-2">User</th>
              <th className="px-4 py-2">Repo</th>
              <th className="px-4 py-2">Branch</th>
              <th className="px-4 py-2">Model</th>
              <th className="px-4 py-2 text-right">Messages</th>
              <th className="px-4 py-2 text-right">Last Active</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {loading && !data && Array.from({ length: 8 }).map((_, i) => (
              <tr key={i}>
                <td className="px-4 py-2.5"><Skeleton className="h-4 w-20" /></td>
                <td className="px-4 py-2.5"><Skeleton className="h-4 w-32" /></td>
                <td className="px-4 py-2.5"><Skeleton className="h-4 w-24" /></td>
                <td className="px-4 py-2.5"><Skeleton className="h-4 w-24" /></td>
                <td className="px-4 py-2.5"><Skeleton className="h-4 w-16" /></td>
                <td className="px-4 py-2.5"><Skeleton className="h-4 w-20" /></td>
                <td className="px-4 py-2.5"><Skeleton className="h-4 w-8 ml-auto" /></td>
                <td className="px-4 py-2.5"><Skeleton className="h-4 w-28 ml-auto" /></td>
              </tr>
            ))}
            {data?.map((s) => (
              <tr
                key={s.id}
                className="group cursor-pointer hover:bg-muted transition-colors"
                onClick={() => router.push(`/sessions/${encodeURIComponent(s.id)}`)}
              >
                <td className="px-4 py-2.5">
                  <SourceBadge source={s.source} />
                </td>
                <td className="px-4 py-2.5 text-muted-foreground font-mono text-xs truncate max-w-[12rem]">
                  {s.id.length > 20 ? s.id.slice(0, 20) + "..." : s.id}
                </td>
                <td className="px-4 py-2.5 text-muted-foreground text-xs truncate max-w-[10rem]">
                  {s.user_email ?? s.device_name ?? (
                    <span className="text-muted-foreground/50">
                      &mdash;
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-muted-foreground text-xs truncate max-w-[10rem]">
                  {s.repo_name ?? s.project_hash?.slice(0, 8) ?? (
                    <span className="text-muted-foreground/50">
                      &mdash;
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-muted-foreground text-xs">
                  {s.git_branch ?? (
                    <span className="text-muted-foreground/50">
                      &mdash;
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-muted-foreground text-xs">
                  {s.model ?? (
                    <span className="text-muted-foreground/50">
                      &mdash;
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted-foreground">
                  {s.message_count}
                </td>
                <td className="px-4 py-2.5 text-right text-muted-foreground text-xs">
                  {s.latest_message
                    ? new Date(s.latest_message).toLocaleString()
                    : "\u2014"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data?.length === 0 && !loading && (
        <EmptyState
          icon={MessageSquare}
          title="No sessions yet"
          description="Check that the daemon is running."
          installCommand="quickcall status"
        />
      )}

      {data && data.length > 0 && (
        <div className="px-4 py-3 border-t border-border flex items-center justify-between">
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
            className="text-xs px-3 py-1.5 rounded bg-muted text-muted-foreground disabled:opacity-40 disabled:cursor-not-allowed hover:bg-muted transition-colors"
          >
            Previous
          </button>
          <span className="text-xs text-muted-foreground">
            Showing {offset + 1}&ndash;{offset + (data?.length ?? 0)}
          </span>
          <button
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={(data?.length ?? 0) < PAGE_SIZE}
            className="text-xs px-3 py-1.5 rounded bg-muted text-muted-foreground disabled:opacity-40 disabled:cursor-not-allowed hover:bg-muted transition-colors"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
