"use client";

import { cn } from "@/lib/utils";
import { TYPE_COLORS, TYPE_COLOR_DEFAULT } from "@/lib/constants";

export function TypeBadge({ type }: { type: string }) {
  const cls = TYPE_COLORS[type] ?? TYPE_COLOR_DEFAULT;
  return (
    <span className={cn("text-[0.6875rem] px-1.5 py-0.5 rounded font-medium", cls)}>
      {type}
    </span>
  );
}
