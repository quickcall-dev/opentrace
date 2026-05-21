export type KnownSource =
  | "claude_code"
  | "codex_cli"
  | "gemini_cli"
  | "cursor"
  | "cursor_vscdb";

export const SOURCE_COLORS: Record<KnownSource, string> = {
  claude_code:
    "bg-orange-500/15 text-orange-600 border-orange-300/30",
  codex_cli:
    "bg-teal-500/15 text-teal-600 border-teal-300/30",
  gemini_cli:
    "bg-blue-500/15 text-blue-600 border-blue-300/30",
  cursor:
    "bg-purple-500/15 text-purple-600 border-purple-300/30",
  cursor_vscdb:
    "bg-cyan-500/15 text-cyan-600 border-cyan-300/30",
};

export const SOURCE_COLOR_DEFAULT =
  "bg-gray-500/15 text-gray-600 border-gray-300/30";

export const TYPE_COLORS: Record<string, string> = {
  user: "bg-cyan-500/15 text-cyan-700",
  assistant: "bg-indigo-500/15 text-indigo-700",
  tool_call: "bg-yellow-500/15 text-yellow-700",
  tool_result: "bg-amber-500/15 text-amber-700",
  system: "bg-gray-500/15 text-gray-600",
};

export const TYPE_COLOR_DEFAULT =
  "bg-gray-500/15 text-gray-600";

/** Polling intervals in milliseconds */
export const POLL_STATS = 30000;
export const POLL_SESSIONS = 30000;
export const POLL_DEVICES = 30000;
export const POLL_FEED = 2000;

/* ── Rich message viewer constants (ported from session viewer) ── */

export const MSG_STYLES: Record<string, { bg: string; border: string; label: string }> = {
  user:        { bg: "bg-blue-50/60",    border: "border-l-blue-400",    label: "text-blue-600" },
  assistant:   { bg: "bg-emerald-50/60", border: "border-l-emerald-400", label: "text-emerald-600" },
  tool_call:   { bg: "bg-amber-50/50",   border: "border-l-amber-400",   label: "text-amber-600" },
  tool_result: { bg: "bg-slate-50",      border: "border-l-slate-300",   label: "text-slate-500" },
  thinking:    { bg: "bg-violet-50/50",  border: "border-l-violet-300",  label: "text-violet-500" },
  system:      { bg: "bg-gray-50",       border: "border-l-gray-300",    label: "text-gray-400" },
};

export const MSG_STYLE_DEFAULT = { bg: "bg-gray-50", border: "border-l-gray-300", label: "text-gray-400" };

export const CODEX_TAGS = new Set([
  "INSTRUCTIONS", "environment_context", "repository_context",
  "git_diff", "git_status", "file_contents", "exec_command", "command",
  "approval_policy", "context", "output", "cwd", "shell",
  "permissions instructions",
]);

export const COMPACTION_SIG = "This session is being continued from a previous conversation";
export const INTERRUPTION_CLAUDE_SIG = "The user doesn't want to proceed with this tool use";
export const INTERRUPTION_CODEX_SIG = "<turn_aborted>";

export const MINIMAP_COLORS: Record<string, string> = {
  user: "#93c5fd",
  assistant: "#6ee7b7",
  tool_call: "#fcd34d",
  tool_result: "#cbd5e1",
  thinking: "#c4b5fd",
  system: "#d1d5db",
};

export const COMPACTION_COLOR = "#f59e0b";
export const INTERRUPTION_COLOR = "#ef4444";
