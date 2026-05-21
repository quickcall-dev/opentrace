"use client";

import { cn } from "@/lib/utils";

export interface SlideGroupItem {
  label: string;
  hidden?: boolean;
}

export interface SlideGroup {
  title: string;
  items: SlideGroupItem[];
}

interface SlideIndicatorProps {
  total: number;
  active: number;
  onNavigate: (index: number) => void;
  groups?: SlideGroup[];
}

export function SlideIndicator({
  total,
  active,
  onNavigate,
  groups,
}: SlideIndicatorProps) {
  // If no groups provided, render simple dot indicators
  if (!groups) {
    return (
      <div className="fixed right-4 top-1/2 -translate-y-1/2 z-50 flex flex-col gap-2">
        {Array.from({ length: total }).map((_, i) => (
          <button
            key={i}
            onClick={() => onNavigate(i)}
            className={cn(
              "w-2.5 h-2.5 rounded-full transition-all duration-300",
              i === active
                ? "bg-accent scale-125"
                : "bg-slate-400/40 hover:bg-slate-400/70"
            )}
            aria-label={`Go to slide ${i + 1}`}
          />
        ))}
      </div>
    );
  }

  // Grouped sidebar navigation
  let globalIndex = 0;

  return (
    <>
      <nav className="fixed left-0 top-0 bottom-0 z-50 w-48 flex flex-col justify-center px-4 pointer-events-auto">
        <div className="flex flex-col gap-4">
          {groups.map((group, gi) => {
            const startIndex = globalIndex;
            const endIndex = startIndex + group.items.length - 1;
            globalIndex += group.items.length;

            if (startIndex >= total) return null;

            const isGroupActive = active >= startIndex && active <= endIndex;

            return (
              <div key={gi}>
                <button
                  className={cn(
                    "text-xs font-semibold uppercase tracking-wider transition-all duration-300 mb-1",
                    isGroupActive
                      ? "text-foreground opacity-100"
                      : "text-muted-foreground opacity-45 hover:opacity-70"
                  )}
                  onClick={() => onNavigate(startIndex)}
                >
                  {group.title}
                </button>
                <div
                  className="overflow-hidden transition-all duration-300"
                  style={{
                    maxHeight: isGroupActive
                      ? `${group.items.length * 2.2}rem`
                      : "0",
                  }}
                >
                  {group.items.map((item, ii) => {
                    const slideIndex = startIndex + ii;
                    if (item.hidden || slideIndex >= total) return null;
                    const isActive = slideIndex === active;
                    return (
                      <button
                        key={ii}
                        className={cn(
                          "block text-xs py-0.5 transition-all duration-300",
                          isActive
                            ? "text-foreground opacity-100"
                            : "text-muted-foreground opacity-60 hover:opacity-90"
                        )}
                        onClick={() => onNavigate(slideIndex)}
                      >
                        {item.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </nav>
      <div className="fixed top-4 left-4 z-[101] text-xs font-semibold text-muted-foreground tabular-nums opacity-60">
        {active + 1}
        <span className="opacity-40 mx-0.5">/</span>
        {total}
      </div>
    </>
  );
}
