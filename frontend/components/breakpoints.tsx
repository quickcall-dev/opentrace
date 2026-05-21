"use client";

interface BreakpointProps {
  time: string;
  label?: string;
}

export function CompactionBreak({ time, label }: BreakpointProps) {
  return (
    <div className="compaction-break">
      <span className="compaction-badge">
        ⚡ {label || "Context compacted"}{" "}
        <span className="text-[0.6875rem] font-mono text-amber-500">{time}</span>
      </span>
    </div>
  );
}

export function InterruptionBreak({ time }: BreakpointProps) {
  return (
    <div className="interruption-break">
      <span className="interruption-badge">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-red-500" /> User
        interrupted{" "}
        <span className="text-[0.6875rem] font-mono text-red-500">{time}</span>
      </span>
    </div>
  );
}
