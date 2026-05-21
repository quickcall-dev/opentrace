"use client";

interface JumpBarProps {
  currentPrompt: number;
  totalPrompts: number;
  onJump: (dir: number) => void;
}

export function JumpBar({ currentPrompt, totalPrompts, onJump }: JumpBarProps) {
  if (totalPrompts < 3) return null;

  return (
    <div className="bg-card border-b border-border px-4 py-1.5 flex items-center gap-2">
      <div className="inline-flex items-center rounded-md border border-border overflow-hidden">
        <button
          onClick={() => onJump(-1)}
          className="px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground active:bg-muted transition-colors border-r border-border"
          title="Previous prompt (k)"
        >
          ▲
        </button>
        <span className="px-2.5 py-1 text-xs text-muted-foreground font-mono tabular-nums bg-muted/50 select-none">
          {currentPrompt}/{totalPrompts}
        </span>
        <button
          onClick={() => onJump(1)}
          className="px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground active:bg-muted transition-colors border-l border-border"
          title="Next prompt (j)"
        >
          ▼
        </button>
      </div>
      <div className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground ml-1">
        <span className="text-[11px] text-muted-foreground/70">prompt</span>
        <kbd className="min-w-[20px] text-center px-1 py-0.5 rounded bg-muted border border-border font-mono font-medium text-muted-foreground shadow-[0_1px_0_0_rgba(0,0,0,0.05)] text-[11px] leading-none">j</kbd>
        <kbd className="min-w-[20px] text-center px-1 py-0.5 rounded bg-muted border border-border font-mono font-medium text-muted-foreground shadow-[0_1px_0_0_rgba(0,0,0,0.05)] text-[11px] leading-none">k</kbd>
      </div>
    </div>
  );
}
