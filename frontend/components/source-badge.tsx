"use client";

import { cn } from "@/lib/utils";
import {
  SOURCE_COLORS,
  SOURCE_COLOR_DEFAULT,
  type KnownSource,
} from "@/lib/constants";

export function SourceBadge({ source }: { source: string }) {
  const cls =
    SOURCE_COLORS[source as KnownSource] ?? SOURCE_COLOR_DEFAULT;
  return (
    <span
      className={cn(
        "text-[0.6875rem] px-1.5 py-0.5 rounded border font-medium",
        cls,
      )}
    >
      {source.replaceAll("_", " ")}
    </span>
  );
}
